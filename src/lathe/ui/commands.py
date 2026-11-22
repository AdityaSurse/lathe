"""Slash command framework, registry, and built-in commands."""

from collections.abc import Callable
from dataclasses import dataclass

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
    ) -> bool:
        """Parse and execute a slash command line. Returns False if REPL should exit."""
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
    """Display session token usage statistics."""
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
        name="/exit",
        description="Gracefully exit Lathe REPL session",
        usage="/exit",
        handler=handle_exit,
    )
)
