"""Sandboxed shell execution tool with environment scrubbing, streaming UI, and process cleanup."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from pydantic import BaseModel, Field
from rich.console import Console

from lathe.safety.permissions import is_blocked_command, scrub_env
from lathe.tools.base import RiskLevel, Tool, ToolContext, ToolResult

DEFAULT_LAST_N_LINES = 100


def kill_process_group(pid: int) -> None:
    """Kill the process group leader and all descendant child processes."""
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


class RunShellArgs(BaseModel):
    """Arguments for executing a shell command in the project root."""

    command: str = Field(
        min_length=1,
        description="The shell command string to execute in workspace root.",
    )
    timeout: int = Field(
        default=120,
        gt=0,
        le=600,
        description="Timeout limit in seconds for command execution (default 120).",
    )


class ShellTool(Tool):
    """Tool to execute shell commands within the workspace root with safety controls."""

    name = "run_shell"
    description = (
        "Execute a shell command within the project workspace root.\n"
        "WHEN TO USE:\n"
        "- Running test suites (e.g. 'pytest tests/tools -v', 'npm test').\n"
        "- Running build tools, formatters, type-checkers, git status, and diagnostics.\n"
        "WHEN NOT TO USE:\n"
        "- Do NOT use to edit or create files (use 'write_file' or 'edit_file' instead).\n"
        "- Do NOT use to read files (use 'read_file' instead).\n"
        "- Do NOT run blocked or dangerous commands (sudo, rm -rf /, dd to devices, fork bombs).\n"
        "- Do NOT run interactive or continuous commands (e.g. vim, nano, top, watch)."
    )
    args_schema = RunShellArgs
    risk_level: RiskLevel = "execute"

    async def _execute(self, args: RunShellArgs, ctx: ToolContext) -> ToolResult:
        # Defense-in-depth: check hard blocklist before launching subprocess
        blocked, pat = is_blocked_command(args.command)
        if blocked:
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"Command '{args.command}' is blocked by security policy: "
                    f"matches forbidden pattern '{pat}'."
                ),
                metadata={"command": args.command, "blocked": True},
            )

        workspace_root = ctx.workspace_root
        clean_env = scrub_env(os.environ)
        console: Console = Console()

        try:
            proc = await asyncio.create_subprocess_shell(
                args.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(workspace_root),
                env=clean_env,
                start_new_session=True,
            )
        except OSError as exc:
            return ToolResult(
                ok=False,
                output="",
                error=f"Failed to start command '{args.command}': {exc}",
                metadata={"command": args.command},
            )

        collected_lines: list[str] = []

        async def _stream_output() -> None:
            if proc.stdout is None:
                return
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line_str = line_bytes.decode("utf-8", errors="replace")
                collected_lines.append(line_str)
                # Stream live output to UI terminal
                console.print(line_str, end="", markup=False)

        try:
            await asyncio.wait_for(_stream_output(), timeout=args.timeout)
            await proc.wait()
        except TimeoutError:
            kill_process_group(proc.pid)
            await proc.wait()
            total = len(collected_lines)
            last_lines = (
                "".join(collected_lines[-DEFAULT_LAST_N_LINES:])
                if total > DEFAULT_LAST_N_LINES
                else "".join(collected_lines)
            )
            return ToolResult(
                ok=False,
                output=last_lines,
                error=(
                    f"Command '{args.command}' timed out after {args.timeout}s "
                    "(process group killed)."
                ),
                metadata={"exit_code": -9, "timed_out": True, "command": args.command},
            )
        except (asyncio.CancelledError, KeyboardInterrupt):
            kill_process_group(proc.pid)
            await proc.wait()
            raise

        returncode = proc.returncode or 0
        total_lines = len(collected_lines)
        if total_lines > DEFAULT_LAST_N_LINES:
            truncated_header = (
                f"... [truncated {total_lines - DEFAULT_LAST_N_LINES} earlier lines]\n"
            )
            output_text = truncated_header + "".join(collected_lines[-DEFAULT_LAST_N_LINES:])
        else:
            output_text = "".join(collected_lines)

        is_ok = returncode == 0
        err_msg = None if is_ok else f"Command failed with exit code {returncode}."

        return ToolResult(
            ok=is_ok,
            output=output_text,
            error=err_msg,
            metadata={
                "exit_code": returncode,
                "command": args.command,
                "total_lines": total_lines,
                "timed_out": False,
            },
        )


# Singleton instances
run_shell = ShellTool()
