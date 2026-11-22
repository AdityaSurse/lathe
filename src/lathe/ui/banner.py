"""Startup banner with ASCII Lathe logo, version, and active models."""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from lathe import __version__
from lathe.config import LatheConfig

ASCII_LOGO = (
    " _       _   _\n"
    "| | __ _| |_| |__   ___\n"
    "| |/ _` | __| '_ \\ / _ \\\n"
    "| | (_| | |_| | | |  __/\n"
    "|_|\\__,_|\\__|_| |_|\\___|"
)


def print_startup_banner(config: LatheConfig, console: Console | None = None) -> None:
    """Render startup banner with logo, version, and model configurations."""
    out_console = console or Console()

    banner_text = Text()
    banner_text.append(ASCII_LOGO + "\n", style="bold cyan")
    banner_text.append("Turn prompts into code. Locally.\n", style="dim italic")
    banner_text.append(
        f"Lathe v{__version__}  ·  Mode: {config.settings.mode}\n\n",
        style="bold white",
    )

    # Roles & Active Models
    coder_info = f"{config.roles.coder.model} ({config.roles.coder.backend})"
    planner_info = f"{config.roles.planner.model} ({config.roles.planner.backend})"
    router_info = f"{config.roles.router.model} ({config.roles.router.backend})"

    banner_text.append("  • Coder:   ", style="bold cyan")
    banner_text.append(f"{coder_info}\n", style="white")
    banner_text.append("  • Planner: ", style="bold magenta")
    banner_text.append(f"{planner_info}\n", style="white")
    banner_text.append("  • Router:  ", style="bold yellow")
    banner_text.append(f"{router_info}\n\n", style="white")

    banner_text.append("Type ", style="dim")
    banner_text.append("/help", style="bold cyan")
    banner_text.append(" for slash commands, ", style="dim")
    banner_text.append("@file", style="bold cyan")
    banner_text.append(" to autocomplete paths, ", style="dim")
    banner_text.append("Alt+Enter", style="bold")
    banner_text.append(" for newline, ", style="dim")
    banner_text.append("Ctrl+D", style="bold")
    banner_text.append(" to exit.", style="dim")

    panel = Panel(
        banner_text,
        border_style="cyan",
        padding=(1, 2),
    )
    out_console.print(panel)
