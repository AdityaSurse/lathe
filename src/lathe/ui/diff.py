"""Diff rendering and formatting utilities for Rich terminal presentation."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from lathe.ui.theme import DIM, PRIMARY, get_console


def create_diff_panel(diff_text: str, filename: str) -> Panel:
    """Create a styled Rich Panel containing a syntax-highlighted unified diff."""
    content = diff_text.strip() if diff_text.strip() else "(No textual changes)"
    syntax = Syntax(
        content,
        "diff",
        theme="monokai",
        line_numbers=True,
        word_wrap=True,
    )
    return Panel(
        syntax,
        title=f"[bold {PRIMARY}]Diff: {filename}[/bold {PRIMARY}]",
        subtitle="[dim]lathe edit_file[/dim]",
        border_style=DIM,
        expand=False,
    )


def print_diff_panel(
    diff_text: str,
    filename: str,
    console: Console | None = None,
) -> Panel:
    """Render and print the unified diff panel to the terminal console."""
    c = console or get_console()
    panel = create_diff_panel(diff_text, filename)
    c.print(panel)
    return panel
