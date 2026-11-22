"""Interactive terminal REPL implementation powered by prompt_toolkit and Rich."""

from __future__ import annotations

import asyncio
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
) -> None:
    """Start interactive Lathe REPL session."""
    active_config = config or load_config(require_secrets=False)
    console = get_console()
    stats = SessionStats()

    # Print startup banner
    print_startup_banner(active_config, console=console)

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
    checkpoint_mgr = get_checkpoint_manager(Path.cwd(), prompt_init=True)

    # Instantiate Agent and attach rich terminal event UI
    from lathe.orchestrator.agent import Agent
    from lathe.ui.agent_view import TerminalAgentUI

    agent = Agent(
        config=active_config,
        permission_engine=permission_engine,
        checkpoint_manager=checkpoint_mgr,
        workspace_root=Path.cwd(),
        console=console,
    )
    agent_ui = TerminalAgentUI(console=console)
    agent_ui.attach(agent.event_bus)

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

    messages: list[Message] = []

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
                break
            continue

        # Run agent loop with Ctrl+C cancellation support
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            task = loop.create_task(agent.run(line, messages=messages))
            loop.run_until_complete(task)
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
) -> None:
    """Entry point to launch the REPL."""
    run_repl(config=config, auto=auto, yolo=yolo)
