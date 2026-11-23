"""Interactive terminal REPL implementation powered by prompt_toolkit and Rich."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from lathe.config import LatheConfig, get_global_config_path, load_config
from lathe.llm.base import LLMError
from lathe.llm.types import Message
from lathe.safety.checkpoints import get_checkpoint_manager
from lathe.safety.permissions import PermissionEngine, PermissionMode
from lathe.ui.banner import print_startup_banner
from lathe.ui.commands import registry
from lathe.ui.completer import LatheCompleter
from lathe.ui.status import SessionStats, render_status_toolbar
from lathe.ui.theme import get_console


def get_history_file_path() -> Path:
    """Return path to prompt history file (~/.config/lathe/history)."""
    return get_global_config_path().parent / "history"


async def _stream_chat_turn(
    client: Any,
    messages: list[Message],
    stats: SessionStats,
    console: Console,
) -> str | None:
    """Stream assistant generation into live Markdown display with metrics."""
    accumulated_text = ""
    start_time = time.perf_counter()
    terminal_usage = None

    try:
        with Live(Markdown(""), refresh_per_second=15, console=console) as live:
            async for chunk in client.chat(messages, stream=True):
                if chunk.delta:
                    accumulated_text += chunk.delta
                    live.update(Markdown(accumulated_text))
                if chunk.done and chunk.usage:
                    terminal_usage = chunk.usage

        elapsed = time.perf_counter() - start_time
        stats.add_usage(terminal_usage)

        if terminal_usage and terminal_usage.completion_tokens > 0:
            tokens = terminal_usage.completion_tokens
            speed = tokens / elapsed if elapsed > 0 else 0.0
            console.print(
                f"\n[dim]─── {tokens} tokens in {elapsed:.2f}s "
                f"({speed:.1f} tok/s) · {client.role_config.model} ───[/dim]\n"
            )
        elif accumulated_text:
            word_count = len(accumulated_text.split())
            speed = word_count / elapsed if elapsed > 0 else 0.0
            console.print(
                f"\n[dim]─── ~{word_count} words in {elapsed:.2f}s "
                f"({speed:.1f} w/s) · {client.role_config.model} ───[/dim]\n"
            )

        return accumulated_text

    except asyncio.CancelledError:
        console.print("\n[yellow]Generation cancelled (Ctrl+C).[/yellow]\n")
        return None
    except LLMError as err:
        console.print(f"\n[red]LLM Error:[/red] {err}\n")
        return None
    except Exception as exc:
        console.print(f"\n[red]Error:[/red] {exc}\n")
        return None


def run_repl(
    config: LatheConfig | None = None,
    auto: bool = False,
    yolo: bool = False,
    resume: bool = False,
    continue_last: bool = False,
    session_id: str | None = None,
    enable_mcp: bool = False,
) -> None:
    """Start interactive Lathe REPL session with optional session resumption."""
    import sys

    from rich.table import Table

    from lathe.memory.sessions import SessionManager
    from lathe.ui.commands import get_pending_prompt

    active_config = config or load_config(require_secrets=False)
    console = get_console()
    stats = SessionStats()
    session_mgr = SessionManager(Path.cwd())

    # Handle session continuation (--continue) or resumption (--resume)
    resolved_session_id = session_id
    resumed_messages: list[Message] = []

    if continue_last and not resolved_session_id:
        latest = session_mgr.get_latest_session()
        if latest:
            resolved_session_id = latest.session_id
        else:
            console.print(
                "[yellow]No saved sessions found to continue. Starting a new session.[/yellow]"
            )

    elif resume and not resolved_session_id:
        sessions = session_mgr.list_sessions()
        if not sessions:
            console.print("[yellow]No saved sessions found to resume.[/yellow]")
        else:
            table = Table(
                title="Saved Lathe Sessions",
                title_style="bold cyan",
                border_style="bright_blue",
                show_header=True,
                header_style="bold white",
            )
            table.add_column("#", style="bold green", width=4)
            table.add_column("Session ID", style="bold cyan", width=12)
            table.add_column("Last Updated", style="dim", width=20)
            table.add_column("Msgs", justify="right", width=6)
            table.add_column("Mode", width=8)
            table.add_column("Title", style="bold white", width=34)

            for idx, s in enumerate(sessions[:10], 1):
                table.add_row(
                    str(idx),
                    s.session_id,
                    s.display_time,
                    str(s.message_count),
                    s.mode,
                    s.title,
                )
            console.print()
            console.print(table)

            if sys.stdin.isatty():
                try:
                    limit_n = min(len(sessions), 10)
                    prompt_msg = f"\n[bold cyan]Select session (1-{limit_n}) or [n]ew: [/bold cyan]"
                    choice_str = console.input(prompt_msg).strip().lower()
                    if choice_str.isdigit():
                        idx = int(choice_str)
                        if 1 <= idx <= len(sessions):
                            resolved_session_id = sessions[idx - 1].session_id
                except (EOFError, KeyboardInterrupt):
                    pass
            else:
                # Non-interactive fallback: pick latest
                resolved_session_id = sessions[0].session_id

    # Load session data if resuming
    if resolved_session_id:
        loaded = session_mgr.load_session(resolved_session_id)
        if loaded:
            resumed_messages = loaded.to_messages()
            console.print(
                f"\n[bold green]✓ Resumed session {resolved_session_id}[/bold green] "
                f"({len(resumed_messages)} messages) · [dim]{loaded.info.title}[/dim]"
            )

    # Print startup banner
    print_startup_banner(active_config, console=console)

    # Project folder guard: check if running in home dir, root, or non-project
    from lathe.safety.guard import check_is_project_folder

    is_proj, guard_msg = check_is_project_folder(Path.cwd())
    if not is_proj:
        console.print(
            f"[yellow]{guard_msg or 'Not in a project folder — cd into a project for full features.'}[/yellow]\n"
        )
        active_config.settings.mode = "single"

    # Determine permission engine mode
    mode = PermissionMode.DEFAULT
    if yolo:
        mode = PermissionMode.YOLO
    elif auto:
        mode = PermissionMode.AUTO

    permission_engine = PermissionEngine(Path.cwd(), mode=mode, console=console)
    if yolo:
        permission_engine.emit_yolo_warning()

    # Initialize checkpoint manager for active workspace
    checkpoint_mgr = get_checkpoint_manager(
        Path.cwd(),
        session_id=resolved_session_id,
        prompt_init=True,
    )

    # Instantiate Agents and attach rich terminal event UI
    from lathe.orchestrator.agent import Agent
    from lathe.orchestrator.dual import DualAgent
    from lathe.orchestrator.router import TaskRouter, get_read_search_tools, get_stats_collector
    from lathe.ui.agent_view import TerminalAgentUI

    stats_collector = get_stats_collector(
        session_id=checkpoint_mgr.session_id, workspace_root=Path.cwd()
    )

    agent = Agent(
        config=active_config,
        permission_engine=permission_engine,
        checkpoint_manager=checkpoint_mgr,
        workspace_root=Path.cwd(),
        console=console,
    )
    dual_agent = DualAgent(
        config=active_config,
        permission_engine=permission_engine,
        checkpoint_manager=checkpoint_mgr,
        workspace_root=Path.cwd(),
        console=console,
        auto_approve=yolo,
    )
    chat_agent = Agent(
        config=active_config,
        tools=get_read_search_tools(),
        permission_engine=permission_engine,
        checkpoint_manager=checkpoint_mgr,
        workspace_root=Path.cwd(),
        console=console,
    )
    router = TaskRouter(
        config=active_config,
        workspace_root=Path.cwd(),
        console=console,
        stats_collector=stats_collector,
    )

    # Optional: Load MCP client tools if configured or requested
    if enable_mcp or active_config.mcp.enabled:
        try:
            from lathe.memory.mcp import load_mcp_tools

            mcp_tools = load_mcp_tools(
                active_config,
                workspace_root=Path.cwd(),
                enabled_override=enable_mcp,
            )
            for m_tool in mcp_tools:
                agent.tools.register(m_tool)
                dual_agent.tools.register(m_tool)
            if mcp_tools:
                console.print(
                    f"[dim]Loaded {len(mcp_tools)} MCP tool(s) from "
                    f"{len(active_config.mcp.servers)} server(s).[/dim]"
                )
        except Exception as mcp_err:
            console.print(f"[yellow]Warning: Failed to load MCP tools: {mcp_err}[/yellow]")

    agent_ui = TerminalAgentUI(console=console)
    agent_ui.attach(agent.event_bus)
    agent_ui.attach(dual_agent.event_bus)
    agent_ui.attach(chat_agent.event_bus)

    # Prepare history & completer
    history_path = get_history_file_path()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history = FileHistory(str(history_path))
    completer = LatheCompleter()

    # Keybindings: Alt+Enter for multiline newline, Enter to submit
    kb = KeyBindings()

    @kb.add("escape", "enter")
    def _insert_newline(event: Any) -> None:
        event.current_buffer.insert_text("\n")

    prompt_session: PromptSession[str] = PromptSession(
        history=history,
        completer=completer,
        key_bindings=kb,
        bottom_toolbar=lambda: render_status_toolbar(active_config, stats),
    )

    messages: list[Message] = list(resumed_messages)

    # Main REPL loop
    while True:
        try:
            user_input = prompt_session.prompt("lathe> ")
        except KeyboardInterrupt:
            # Ctrl+C at prompt clears line without exiting
            console.print("[dim](Use Ctrl+D or /exit to exit)[/dim]")
            continue
        except EOFError:
            # Ctrl+D exits cleanly
            with contextlib.suppress(Exception):
                session_mgr.save_session(
                    session_id=checkpoint_mgr.session_id,
                    messages=messages,
                    checkpoints=checkpoint_mgr.list_checkpoints(),
                    stats=stats_collector,
                    mode=getattr(active_config.settings, "mode", "auto"),
                )
            console.print("\n[dim]Goodbye![/dim]")
            break

        line = user_input.strip()
        if not line:
            continue

        # Handle slash commands
        if line.startswith("/"):
            should_continue = registry.execute(
                line, active_config, stats, console, messages=messages
            )
            if not should_continue:
                with contextlib.suppress(Exception):
                    session_mgr.save_session(
                        session_id=checkpoint_mgr.session_id,
                        messages=messages,
                        checkpoints=checkpoint_mgr.list_checkpoints(),
                        stats=stats_collector,
                        mode=getattr(active_config.settings, "mode", "auto"),
                    )
                break
            pending = get_pending_prompt()
            if pending:
                line = pending
            else:
                continue

        # Run agent loop with Ctrl+C cancellation support
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            current_mode = getattr(active_config.settings, "mode", "auto")

            if current_mode == "dual":
                coro = dual_agent.run(line)
            elif current_mode == "single":
                coro = agent.run(line, messages=messages)
            else:  # "auto"

                async def _routed_step(prompt: str = line) -> str:
                    return await router.route_and_execute(
                        prompt,
                        messages=messages,
                        auto_approve=auto or yolo,
                        yolo=yolo,
                        agent=agent,
                        dual_agent=dual_agent,
                        chat_agent=chat_agent,
                    )

                coro = _routed_step()

            task = loop.create_task(coro)
            loop.run_until_complete(task)

            # Auto-save session state to .lathe/sessions/<session_id>/
            with contextlib.suppress(Exception):
                session_mgr.save_session(
                    session_id=checkpoint_mgr.session_id,
                    messages=messages,
                    checkpoints=checkpoint_mgr.list_checkpoints(),
                    stats=stats_collector,
                    mode=current_mode,
                )

        except KeyboardInterrupt:
            console.print("\n[yellow]Generation cancelled (Ctrl+C).[/yellow]\n")
        except LLMError as err:
            console.print(f"\n[red]LLM Error:[/red] {err}\n")
        except Exception as exc:
            console.print(f"\n[red]Error:[/red] {exc}\n")
        finally:
            loop.close()


def start_repl(
    config: LatheConfig | None = None,
    auto: bool = False,
    yolo: bool = False,
    resume: bool = False,
    continue_last: bool = False,
    session_id: str | None = None,
    enable_mcp: bool = False,
) -> None:
    """Entry point to launch the REPL."""
    run_repl(
        config=config,
        auto=auto,
        yolo=yolo,
        resume=resume,
        continue_last=continue_last,
        session_id=session_id,
        enable_mcp=enable_mcp,
    )
