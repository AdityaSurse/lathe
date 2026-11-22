"""Slash command framework, registry, and built-in commands."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.table import Table

from lathe.config import LatheConfig, get_project_config_path, set_config_value
from lathe.ui.status import SessionStats


@dataclass
class SlashCommand:
    """Definition of a slash command available in the REPL."""

    name: str
    description: str
    usage: str
    handler: Callable[..., bool]  # Returns False to signal REPL exit


_ACTIVE_MESSAGES: list[Any] = []


def set_active_messages(messages: list[Any]) -> None:
    """Set active conversation messages for slash commands inspection and compaction."""
    global _ACTIVE_MESSAGES
    _ACTIVE_MESSAGES = messages


def get_active_messages() -> list[Any]:
    """Retrieve active conversation messages."""
    return _ACTIVE_MESSAGES


class SlashCommandRegistry:
    """Registry managing available interactive slash commands."""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> None:
        """Register a new slash command."""
        self._commands[command.name.lower()] = command

    def get(self, name: str) -> SlashCommand | None:
        """Retrieve command by name (case-insensitive)."""
        return self._commands.get(name.lower())

    def list_commands(self) -> list[SlashCommand]:
        """Return list of all registered commands sorted by name."""
        return sorted(self._commands.values(), key=lambda c: c.name)

    def execute(
        self,
        line: str,
        config: LatheConfig,
        stats: SessionStats,
        console: Console,
        messages: list[Any] | None = None,
    ) -> bool:
        """Parse and execute a slash command line. Returns False if REPL should exit."""
        if messages is not None:
            set_active_messages(messages)

        parts = line.strip().split()
        if not parts:
            return True

        cmd_name = parts[0]
        args = parts[1:]

        command = self.get(cmd_name)
        if not command:
            console.print(
                f"[red]Unknown slash command:[/red] {cmd_name}. "
                "Type [bold cyan]/help[/bold cyan] for available commands."
            )
            return True

        return command.handler(args, config, stats, console)


# --- Built-in Command Handlers ---


def handle_help(
    args: list[str],
    config: LatheConfig,
    stats: SessionStats,
    console: Console,
) -> bool:
    """List all registered slash commands in a Rich table."""
    table = Table(
        title="Lathe Slash Commands",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Command", style="bold cyan", width=16)
    table.add_column("Description", width=38)
    table.add_column("Usage", style="dim", width=36)

    for cmd in registry.list_commands():
        table.add_row(cmd.name, cmd.description, cmd.usage)

    console.print(table)
    return True


def handle_model(
    args: list[str],
    config: LatheConfig,
    stats: SessionStats,
    console: Console,
) -> bool:
    """Update active model for a role: /model <role> <model_id>."""
    if len(args) < 2:
        console.print("[yellow]Usage:[/yellow] /model <role> <model_id>")
        console.print("[dim]Roles: coder, planner, router, reviewer[/dim]")
        return True

    role_name = args[0].lower()
    model_id = args[1]

    if role_name not in ("coder", "planner", "router", "reviewer"):
        console.print(
            f"[red]Invalid role:[/red] {role_name}. Must be coder, planner, router, or reviewer."
        )
        return True

    # Update in-memory configuration
    if role_name == "coder":
        config.roles.coder.model = model_id
    elif role_name == "planner":
        config.roles.planner.model = model_id
    elif role_name == "router":
        config.roles.router.model = model_id
    elif role_name == "reviewer":
        reviewer = config.get_reviewer()
        reviewer.model = model_id

    # Persist to lathe.toml if present
    target_file = get_project_config_path()
    if target_file.exists():
        try:
            set_config_value(f"roles.{role_name}.model", model_id, target_file)
            console.print(
                f"[green]Assigned {role_name} -> '{model_id}' (persisted to lathe.toml)[/green]"
            )
            return True
        except Exception:
            pass

    console.print(f"[green]Assigned {role_name} -> '{model_id}' (active session)[/green]")
    return True


def handle_mode(
    args: list[str],
    config: LatheConfig,
    stats: SessionStats,
    console: Console,
) -> bool:
    """Toggle execution mode: /mode single|dual."""
    if not args or args[0].lower() not in ("single", "dual"):
        console.print("[yellow]Usage:[/yellow] /mode single|dual")
        console.print(f"[dim]Current mode: {config.settings.mode}[/dim]")
        return True

    new_mode = args[0].lower()
    config.settings.mode = new_mode  # type: ignore[assignment]

    target_file = get_project_config_path()
    if target_file.exists():
        try:
            set_config_value("settings.mode", new_mode, target_file)
            console.print(f"[green]Mode set to '{new_mode}' (persisted to lathe.toml)[/green]")
            return True
        except Exception:
            pass

    console.print(f"[green]Mode switched to '{new_mode}'[/green]")
    return True


def handle_clear(
    args: list[str],
    config: LatheConfig,
    stats: SessionStats,
    console: Console,
) -> bool:
    """Clear terminal screen."""
    console.clear()
    return True


def handle_tokens(
    args: list[str],
    config: LatheConfig,
    stats: SessionStats,
    console: Console,
) -> bool:
    """Display session token usage statistics and colored budget bar chart."""
    from lathe.context.budget import BudgetAllocator

    table = Table(
        title="Session Token Consumption",
        title_style="bold cyan",
        border_style="bright_blue",
    )
    table.add_column("Metric", style="bold", width=24)
    table.add_column("Count", justify="right", width=16)

    table.add_row("Prompt Tokens", f"{stats.prompt_tokens:,}")
    table.add_row("Completion Tokens", f"{stats.completion_tokens:,}")
    table.add_row("Total Tokens", f"{stats.total_tokens:,}")
    table.add_row("Queries Executed", str(stats.request_count))

    console.print(table)

    # Render category breakdown bar chart
    coder_cfg = config.roles.coder
    allocator = BudgetAllocator(
        context_window=coder_cfg.context_window,
        max_tokens=coder_cfg.max_tokens,
        model_name=coder_cfg.model,
    )
    active_msgs = get_active_messages()
    usage = allocator.calculate_usage(active_msgs)
    allocator.render_budget_bar_chart(usage, console=console)
    return True


def handle_compact(
    args: list[str],
    config: LatheConfig,
    stats: SessionStats,
    console: Console,
) -> bool:
    """Force context compaction to free tokens within budget."""
    from lathe.context.budget import BudgetAllocator, compact_context

    active_msgs = get_active_messages()
    if not active_msgs:
        console.print("[dim]No active conversation messages to compact.[/dim]")
        return True

    coder_cfg = config.roles.coder
    allocator = BudgetAllocator(
        context_window=coder_cfg.context_window,
        max_tokens=coder_cfg.max_tokens,
        model_name=coder_cfg.model,
    )

    before_usage = allocator.calculate_usage(active_msgs)
    compacted, did_compact, note = compact_context(active_msgs, allocator, force=True)

    if did_compact:
        active_msgs.clear()
        active_msgs.extend(compacted)
        after_usage = allocator.calculate_usage(active_msgs)
        freed = max(0, before_usage.total_used - after_usage.total_used)
        used_b = before_usage.total_used
        used_a = after_usage.total_used
        pct_a = after_usage.usage_ratio * 100
        console.print(
            f"[green]✓ Context compacted successfully:[/green] freed [bold]{freed:,}[/bold] tokens "
            f"({used_b:,} → {used_a:,} tokens · {pct_a:.1f}% capacity).\n"
            f"[dim]{note}[/dim]"
        )
    else:
        console.print(f"[yellow]Compaction status:[/yellow] {note}")

    return True


def handle_exit(
    args: list[str],
    config: LatheConfig,
    stats: SessionStats,
    console: Console,
) -> bool:
    """Exit Lathe REPL."""
    console.print("[dim]Exiting Lathe session. Goodbye![/dim]")
    return False


def handle_undo(
    args: list[str],
    config: LatheConfig,
    stats: SessionStats,
    console: Console,
) -> bool:
    """Restore the last checkpoint taken before modifications."""
    from lathe.safety.checkpoints import get_checkpoint_manager

    cm = get_checkpoint_manager()
    if not cm.is_enabled:
        console.print("[yellow]Checkpoints are disabled (not a git repository).[/yellow]")
        return True

    undone_ckpt = cm.undo()
    if undone_ckpt:
        console.print(
            f"[green]✓ Undone to checkpoint #{undone_ckpt.number}:[/green] "
            f"{undone_ckpt.description} [dim]({undone_ckpt.formatted_time})[/dim]"
        )
    else:
        console.print("[yellow]No earlier checkpoints available to undo.[/yellow]")
    return True


def handle_checkpoints(
    args: list[str],
    config: LatheConfig,
    stats: SessionStats,
    console: Console,
) -> bool:
    """List all session checkpoints with timestamps and changed files."""
    from lathe.safety.checkpoints import get_checkpoint_manager

    cm = get_checkpoint_manager()
    if not cm.is_enabled:
        console.print("[yellow]Checkpoints are disabled (not a git repository).[/yellow]")
        return True

    ckpts = cm.list_checkpoints()
    if not ckpts:
        console.print("[dim]No checkpoints created in this session yet.[/dim]")
        return True

    table = Table(
        title="Session Checkpoints",
        title_style="bold cyan",
        border_style="bright_blue",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("#", style="bold green", width=4)
    table.add_column("Time", style="dim", width=10)
    table.add_column("Description", width=36)
    table.add_column("Changed Files", style="cyan", width=30)

    for c in ckpts:
        changed_preview = ", ".join(c.changed_files[:3])
        if len(c.changed_files) > 3:
            changed_preview += f" (+{len(c.changed_files) - 3} more)"
        table.add_row(str(c.number), c.formatted_time, c.description, changed_preview or "(none)")

    console.print(table)
    return True


def handle_restore(
    args: list[str],
    config: LatheConfig,
    stats: SessionStats,
    console: Console,
) -> bool:
    """Restore workspace to a specific checkpoint number: /restore <n>."""
    from lathe.safety.checkpoints import get_checkpoint_manager

    if not args:
        console.print("[yellow]Usage:[/yellow] /restore <n>")
        return True

    try:
        n = int(args[0])
    except ValueError:
        console.print(f"[red]Invalid checkpoint number:[/red] '{args[0]}'. Must be an integer.")
        return True

    cm = get_checkpoint_manager()
    if not cm.is_enabled:
        console.print("[yellow]Checkpoints are disabled (not a git repository).[/yellow]")
        return True

    if cm.restore(n):
        console.print(f"[green]✓ Successfully restored workspace to checkpoint #{n}[/green]")
    else:
        console.print(
            f"[red]Failed to restore to checkpoint #{n}. "
            "Check /checkpoints for valid numbers.[/red]"
        )
    return True


def handle_diff(
    args: list[str],
    config: LatheConfig,
    stats: SessionStats,
    console: Console,
) -> bool:
    """Display unified diff of all modifications made during this session."""
    from rich.panel import Panel
    from rich.syntax import Syntax

    from lathe.safety.checkpoints import get_checkpoint_manager

    cm = get_checkpoint_manager()
    if not cm.is_enabled:
        console.print("[yellow]Checkpoints are disabled (not a git repository).[/yellow]")
        return True

    diff_text = cm.get_session_diff()
    if not diff_text.strip():
        console.print(
            "[dim]No changes made in this session (working tree matches initial state).[/dim]"
        )
        return True

    syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=True)
    panel = Panel(
        syntax,
        title="[bold cyan]Session Changes (Unified Diff)[/bold cyan]",
        border_style="cyan",
    )
    console.print(panel)
    return True


# Register all built-in commands
registry = SlashCommandRegistry()
registry.register(
    SlashCommand(
        name="/help",
        description="Show list of available slash commands",
        usage="/help",
        handler=handle_help,
    )
)
registry.register(
    SlashCommand(
        name="/model",
        description="Switch active model for an agent role",
        usage="/model <role> <model_id>",
        handler=handle_model,
    )
)
registry.register(
    SlashCommand(
        name="/mode",
        description="Switch between single (coder) and dual (planner+coder) mode",
        usage="/mode single|dual",
        handler=handle_mode,
    )
)
registry.register(
    SlashCommand(
        name="/clear",
        description="Clear terminal screen",
        usage="/clear",
        handler=handle_clear,
    )
)
registry.register(
    SlashCommand(
        name="/tokens",
        description="View token usage and statistics for current session",
        usage="/tokens",
        handler=handle_tokens,
    )
)
registry.register(
    SlashCommand(
        name="/compact",
        description="Force compaction of the conversation context to free token budget",
        usage="/compact",
        handler=handle_compact,
    )
)
registry.register(
    SlashCommand(
        name="/exit",
        description="Gracefully exit Lathe REPL session",
        usage="/exit",
        handler=handle_exit,
    )
)
registry.register(
    SlashCommand(
        name="/undo",
        description="Restore the last checkpoint taken before modifications",
        usage="/undo",
        handler=handle_undo,
    )
)
registry.register(
    SlashCommand(
        name="/checkpoints",
        description="List all session checkpoints with timestamps and changed files",
        usage="/checkpoints",
        handler=handle_checkpoints,
    )
)
registry.register(
    SlashCommand(
        name="/restore",
        description="Restore workspace to a specific checkpoint number: /restore <n>",
        usage="/restore <n>",
        handler=handle_restore,
    )
)
registry.register(
    SlashCommand(
        name="/diff",
        description="Show unified diff of all modifications made during this session",
        usage="/diff",
        handler=handle_diff,
    )
)
