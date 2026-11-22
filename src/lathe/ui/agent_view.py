"""Terminal UI event listener for streaming and rendering agent execution steps."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown

from lathe.orchestrator.events import (
    AgentEvent,
    AgentHaltEvent,
    DiffEvent,
    EventBus,
    FinalAnswerEvent,
    NudgeEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from lathe.ui.diff import create_diff_panel
from lathe.ui.theme import ERROR, PRIMARY, SUCCESS, WARNING, get_console

TOOL_ICONS: dict[str, str] = {
    "read_file": "📖",
    "list_dir": "📁",
    "glob": "🔍",
    "write_file": "📄",
    "edit_file": "✏️",
    "run_shell": "⚡",
    "git_status": "🌿",
    "git_diff": "🌿",
    "git_log": "🌿",
    "git_commit": "🌿",
    "echo": "📢",
}


def format_args_summary(tool_name: str, args: dict[str, Any]) -> str:
    """Format tool arguments into a compact, human-readable one-line summary."""
    name = tool_name.lower()
    if name == "read_file":
        path = args.get("path", "")
        start = args.get("start_line")
        end = args.get("end_line")
        if start is not None and end is not None:
            return f"{path} [lines {start}-{end}]"
        if start is not None:
            return f"{path} [from line {start}]"
        return str(path)

    if name == "edit_file":
        path = args.get("path", "")
        edits = args.get("edits", [])
        num_edits = len(edits) if isinstance(edits, list) else 1
        return f"{path} ({num_edits} edit{'s' if num_edits != 1 else ''})"

    if name == "write_file":
        path = args.get("path", "")
        content = args.get("content", "")
        length = len(content) if isinstance(content, str) else 0
        return f"{path} ({length} bytes)"

    if name == "run_shell":
        cmd = str(args.get("command", "")).strip()
        if len(cmd) > 60:
            return f'"{cmd[:57]}..."'
        return f'"{cmd}"'

    if name == "list_dir":
        path = args.get("path", ".")
        depth = args.get("depth", 2)
        return f"{path} (depth={depth})"

    if name == "glob":
        pattern = args.get("pattern", "")
        return f'"{pattern}"'

    if name == "git_commit":
        msg = str(args.get("message", "")).strip()
        if len(msg) > 50:
            return f'"{msg[:47]}..."'
        return f'"{msg}"'

    if name in ("git_status", "git_log"):
        return ""

    if name == "git_diff":
        path = args.get("path")
        staged = args.get("staged", False)
        prefix = "staged" if staged else "unstaged"
        return f"{prefix} {path}" if path else prefix

    # Generic fallback
    compact = ", ".join(f"{k}={v}" for k, v in args.items() if not isinstance(v, (dict, list)))
    return compact[:60]


class TerminalAgentUI:
    """Listens to Agent event bus and renders execution steps into rich terminal components."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or get_console()
        self._current_step = 0
        self._last_thinking_step = -1

    def attach(self, bus: EventBus) -> None:
        """Subscribe this UI view to the given agent event bus."""
        bus.subscribe(self.on_event)

    def detach(self, bus: EventBus) -> None:
        """Unsubscribe from the agent event bus."""
        bus.unsubscribe(self.on_event)

    def on_event(self, event: AgentEvent) -> None:
        """Handle incoming typed agent events."""
        if isinstance(event, ThinkingEvent):
            self._handle_thinking(event)
        elif isinstance(event, ToolStartEvent):
            self._handle_tool_start(event)
        elif isinstance(event, ToolEndEvent):
            self._handle_tool_end(event)
        elif isinstance(event, DiffEvent):
            self._handle_diff(event)
        elif isinstance(event, NudgeEvent):
            self._handle_nudge(event)
        elif isinstance(event, AgentHaltEvent):
            self._handle_halt(event)
        elif isinstance(event, FinalAnswerEvent):
            self._handle_final(event)

    def _handle_thinking(self, event: ThinkingEvent) -> None:
        """Optionally display high-level thinking or reasoning if non-empty."""
        # Only print thinking header once per step if there is meaningful text
        if event.content and event.step_index != self._last_thinking_step:
            first_line = event.content.strip().split("\n")[0]
            if len(first_line) > 80:
                first_line = first_line[:77] + "..."
            self.console.print(f"[dim]💭 {first_line}[/dim]")
            self._last_thinking_step = event.step_index

    def _handle_tool_start(self, event: ToolStartEvent) -> None:
        """Render a compact line for the started tool."""
        icon = TOOL_ICONS.get(event.tool_name.lower(), "⚙️")
        summary = format_args_summary(event.tool_name, event.arguments)
        summary_str = f" [dim]{summary}[/dim]" if summary else ""
        tool_label = f"[bold {PRIMARY}]{event.tool_name}[/bold {PRIMARY}]"
        self.console.print(f"  {icon} {tool_label}{summary_str} [dim]...[/dim]")

    def _handle_tool_end(self, event: ToolEndEvent) -> None:
        """Update or render the tool status and duration."""
        if event.result.ok:
            status_symbol = f"[bold {SUCCESS}]✓[/bold {SUCCESS}]"
        else:
            status_symbol = f"[bold {ERROR}]✗[/bold {ERROR}]"
        duration_str = f"[dim]({event.duration_ms:.0f}ms)[/dim]"

        if not event.result.ok:
            error_preview = event.result.error or "Unknown error"
            self.console.print(
                f"    {status_symbol} [red]Failed[/red] {duration_str}: [dim]{error_preview}[/dim]"
            )
        else:
            # If shell output or summary, display indented
            if event.tool_name.lower() == "run_shell" and event.result.output.strip():
                lines = event.result.output.strip().splitlines()
                preview = lines[-1] if len(lines) == 1 else f"{len(lines)} lines of output"
                self.console.print(
                    f"    {status_symbol} [green]Done[/green] {duration_str} [dim]· {preview}[/dim]"
                )
            else:
                self.console.print(f"    {status_symbol} [green]Done[/green] {duration_str}")

    def _handle_diff(self, event: DiffEvent) -> None:
        """Display styled unified diff panel."""
        panel = create_diff_panel(event.diff, event.path)
        self.console.print(panel)

    def _handle_nudge(self, event: NudgeEvent) -> None:
        """Display loop repetition warning nudge."""
        warning_tag = f"[bold {WARNING}]⚠ Loop Warning ({event.repetition_count}x)[/bold {WARNING}]"
        self.console.print(f"\n  {warning_tag}: {event.message}\n")

    def _handle_halt(self, event: AgentHaltEvent) -> None:
        """Display agent halt notification."""
        halt_tag = f"[bold {ERROR}]⏹ Agent Stopped:[/bold {ERROR}]"
        self.console.print(f"\n  {halt_tag} {event.reason} [dim](step {event.total_steps})[/dim]\n")

    def _handle_final(self, event: FinalAnswerEvent) -> None:
        """Render final answer as rich Markdown."""
        self.console.print()
        self.console.print(Markdown(event.content))
        self.console.print()
