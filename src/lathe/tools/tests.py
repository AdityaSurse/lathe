"""Test runner tool for Lathe: auto-detects and executes project test suites.

Supports:
- Python: pytest
- Node/JS/TS: npm test, pnpm test, yarn test
- Rust: cargo test
- Go: go test ./...
- C/C++: ctest
- Make: make test
- Custom: configured [project].test_command from lathe.toml

Parses pass/fail metrics and extracts the first failing test's output for model self-correction.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from lathe.config import LatheConfig, load_config
from lathe.safety.permissions import scrub_env
from lathe.tools.base import RiskLevel, Tool, ToolContext, ToolResult


@dataclass
class TestRunResult:
    """Structured result of executing a project test suite."""

    __test__ = False

    command: str
    exit_code: int
    passed: int
    failed: int
    total: int
    failing_output: str | None = None
    raw_output: str = ""
    duration_s: float = 0.0

    @property
    def is_success(self) -> bool:
        """Whether the test run passed completely with zero failures."""
        return self.exit_code == 0 and self.failed == 0


def detect_test_command(
    workspace_root: Path | str,
    config_test_cmd: str | None = None,
) -> str | None:
    """Auto-detect project's test command based on workspace files and configuration."""
    if config_test_cmd and config_test_cmd.strip():
        return config_test_cmd.strip()

    ws = Path(workspace_root).resolve()

    # 1. Python (pytest)
    python_markers = [
        "pytest.ini",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
    ]
    has_tests_dir = (ws / "tests").is_dir()
    has_test_files = any(ws.glob("test_*.py")) or any(ws.glob("*_test.py"))
    if any((ws / marker).is_file() for marker in python_markers) or has_tests_dir or has_test_files:
        return "pytest"

    # 2. Node / JS / TS (npm/pnpm/yarn test)
    if (ws / "package.json").is_file():
        if (ws / "pnpm-lock.yaml").is_file():
            return "pnpm test"
        if (ws / "yarn.lock").is_file():
            return "yarn test"
        return "npm test"

    # 3. Rust (cargo test)
    if (ws / "Cargo.toml").is_file():
        return "cargo test"

    # 4. Go (go test ./...)
    if (ws / "go.mod").is_file() or any(ws.glob("*.go")):
        return "go test ./..."

    # 5. C/C++ CTest
    if (ws / "CTestTestfile.cmake").is_file() or (ws / "CMakeLists.txt").is_file():
        return "ctest"

    # 6. Makefile (make test)
    for makefile_name in ("Makefile", "makefile", "GNUmakefile"):
        mf = ws / makefile_name
        if mf.is_file():
            try:
                content = mf.read_text(encoding="utf-8", errors="ignore")
                if re.search(r"^test\s*:", content, re.MULTILINE):
                    return "make test"
            except Exception:
                pass

    return None


def parse_test_output(
    command: str,
    exit_code: int,
    output: str,
    duration_s: float = 0.0,
) -> TestRunResult:
    """Parse test output for pass/fail counts and extract the first failing test details."""
    passed = 0
    failed = 0
    failing_output: str | None = None
    cmd_lower = command.lower()

    # 1. Pytest parsing
    if "pytest" in cmd_lower:
        passed_match = re.search(r"(\d+)\s+passed\b", output)
        failed_match = re.search(r"(\d+)\s+failed\b", output)
        error_match = re.search(r"(\d+)\s+error(?:s)?\b", output)

        if passed_match:
            passed = int(passed_match.group(1))
        if failed_match:
            failed += int(failed_match.group(1))
        if error_match:
            failed += int(error_match.group(1))

        if failed > 0 or exit_code != 0:
            # Capture failure block
            pytest_pattern = (
                r"(_{3,}\s+[\w\.\:\-\[\]\<\>\(\)]+\s+_{3,}[\s\S]*?)"
                r"(?:_{3,}\s+[\w\.\:\-\[\]\<\>\(\)]+\s+_{3,}|={3,}\s+short test summary|\Z)"
            )
            fail_block = re.search(pytest_pattern, output)
            if fail_block:
                failing_output = fail_block.group(1).strip()
            else:
                # Capture summary lines containing FAILED / ERROR
                err_lines = [
                    line
                    for line in output.splitlines()
                    if "FAILED" in line or "ERROR" in line or "Error:" in line
                ]
                if err_lines:
                    failing_output = "\n".join(err_lines[:15])

    # 2. Cargo test parsing
    elif "cargo" in cmd_lower:
        # test result: FAILED. 4 passed; 1 failed; 0 ignored;
        cargo_res = re.search(
            r"test result:\s*(?:ok|FAILED)\.\s*(\d+)\s*passed;\s*(\d+)\s*failed;",
            output,
        )
        if cargo_res:
            passed = int(cargo_res.group(1))
            failed = int(cargo_res.group(2))

        if failed > 0 or exit_code != 0:
            fail_block = re.search(r"(failures:[\s\S]*?)(?:test result:|\Z)", output)
            if fail_block:
                failing_output = fail_block.group(1).strip()

    # 3. Go test parsing
    elif "go test" in cmd_lower:
        passed = len(re.findall(r"--- PASS:", output))
        failed = len(re.findall(r"--- FAIL:", output))
        if failed > 0 or exit_code != 0:
            fail_block = re.search(r"(--- FAIL:[\s\S]*?)(?:--- PASS:|FAIL\s|\Z)", output)
            if fail_block:
                failing_output = fail_block.group(1).strip()

    # 4. Jest / Vitest / npm test parsing
    elif any(pkg in cmd_lower for pkg in ("npm", "pnpm", "yarn", "jest", "vitest")):
        jest_match = re.search(r"Tests:\s*(?:(\d+)\s*failed,\s*)?(\d+)\s*passed", output)
        if jest_match:
            failed = int(jest_match.group(1)) if jest_match.group(1) else 0
            passed = int(jest_match.group(2)) if jest_match.group(2) else 0
        else:
            passing_m = re.search(r"(\d+)\s+passing", output)
            failing_m = re.search(r"(\d+)\s+failing", output)
            if passing_m:
                passed = int(passing_m.group(1))
            if failing_m:
                failed = int(failing_m.group(1))

        if failed > 0 or exit_code != 0:
            fail_lines = [
                line
                for line in output.splitlines()
                if "●" in line or "FAIL" in line or "Error:" in line
            ]
            if fail_lines:
                failing_output = "\n".join(fail_lines[:20])

    # 5. Generic fallback when specific runner counts weren't parsed
    if passed == 0 and failed == 0:
        if exit_code == 0:
            passed = 1
            failed = 0
        else:
            passed = 0
            failed = 1
            # Fallback failing output: trailing non-empty output
            lines = [line for line in output.splitlines() if line.strip()]
            failing_output = "\n".join(lines[-20:]) if lines else "Test command exited non-zero."

    # If test failed but no specific failure block was extracted, take trailing lines
    if (failed > 0 or exit_code != 0) and not failing_output:
        lines = [line for line in output.splitlines() if line.strip()]
        failing_output = "\n".join(lines[-20:]) if lines else "Test run failed."

    # Truncate failing output if overly long to preserve context budget
    if failing_output and len(failing_output) > 2500:
        failing_output = failing_output[:2400] + "\n... [truncated remaining test error output]"

    return TestRunResult(
        command=command,
        exit_code=exit_code,
        passed=passed,
        failed=failed,
        total=passed + failed,
        failing_output=failing_output,
        raw_output=output,
        duration_s=duration_s,
    )


def run_tests_helper(
    workspace_root: Path | str,
    config: LatheConfig | None = None,
    command_override: str | None = None,
    timeout: int = 120,
) -> TestRunResult:
    """Execute the project test command in workspace_root and return structured results."""
    ws = Path(workspace_root).resolve()
    active_cfg = config or load_config(project_dir=ws, require_secrets=False)

    configured_cmd = active_cfg.project.test_command if hasattr(active_cfg, "project") else None
    cmd = command_override or detect_test_command(ws, configured_cmd)

    if not cmd:
        return TestRunResult(
            command="none",
            exit_code=0,
            passed=0,
            failed=0,
            total=0,
            failing_output=None,
            raw_output="No test runner detected in workspace and [project].test_command not set.",
            duration_s=0.0,
        )

    # Scrub secrets from environment
    env = scrub_env(os.environ.copy())

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.perf_counter() - t0
        raw_output = f"{proc.stdout}\n{proc.stderr}".strip()
        return parse_test_output(cmd, proc.returncode, raw_output, duration_s=duration)

    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - t0
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        raw = f"{out}\n{err}".strip()
        return TestRunResult(
            command=cmd,
            exit_code=124,
            passed=0,
            failed=1,
            total=1,
            failing_output=f"Test run timed out after {timeout} seconds.",
            raw_output=raw,
            duration_s=duration,
        )
    except Exception as err:
        duration = time.perf_counter() - t0
        return TestRunResult(
            command=cmd,
            exit_code=1,
            passed=0,
            failed=1,
            total=1,
            failing_output=f"Failed to execute test command '{cmd}': {err}",
            raw_output=str(err),
            duration_s=duration,
        )


class RunTestsArgs(BaseModel):
    """Arguments for run_tests tool."""

    command: str | None = Field(
        default=None,
        description=(
            "Optional test command override (e.g. 'pytest tests/test_foo.py -v', 'npm test'). "
            "If omitted, auto-detects based on workspace project files or [project].test_command."
        ),
    )


class RunTestsTool(Tool):
    """Tool that executes project test suites and parses pass/fail metrics and error details."""

    name: str = "run_tests"
    description: str = (
        "Execute project unit tests with auto-detected test runner (pytest, npm test, cargo "
        "test, go test, make test, ctest) or configured [project].test_command. Returns pass/fail "
        "counts, execution status, and the details of any failing tests."
    )
    args_schema: type[BaseModel] = RunTestsArgs
    risk_level: RiskLevel = "execute"

    async def _execute(self, args: Any, ctx: ToolContext) -> ToolResult:
        """Run project tests in workspace and return structured output."""
        typed_args: RunTestsArgs = (
            args if isinstance(args, RunTestsArgs) else RunTestsArgs.model_validate(args)
        )
        res = run_tests_helper(
            workspace_root=ctx.workspace_root,
            command_override=typed_args.command,
        )

        status_str = "PASSED" if res.is_success else "FAILED"
        summary_lines = [
            f"Test Runner: {res.command}",
            f"Status: {status_str} (exit code: {res.exit_code})",
            f"Results: {res.passed} passed, {res.failed} failed ({res.duration_s:.2f}s)",
        ]

        if res.failing_output:
            summary_lines.extend(["", "Failing Test Details:", res.failing_output])

        output_text = "\n".join(summary_lines)

        return ToolResult(
            ok=res.is_success,
            output=output_text,
            error=res.failing_output if not res.is_success else None,
            metadata={
                "command": res.command,
                "exit_code": res.exit_code,
                "passed": res.passed,
                "failed": res.failed,
                "total": res.total,
                "duration_s": res.duration_s,
            },
        )
