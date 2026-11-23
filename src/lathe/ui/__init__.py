"""User interface package providing Rich themes, status bars, slash commands, diffs, and REPL."""

from typing import Any

from lathe.ui.banner import print_startup_banner
from lathe.ui.diff import create_diff_panel, print_diff_panel
from lathe.ui.status import SessionStats, get_git_branch, get_repo_name, render_status_toolbar
from lathe.ui.theme import LATHE_THEME, get_console

__all__ = [
    "LATHE_THEME",
    "LatheCompleter",
    "SessionStats",
    "SlashCommand",
    "SlashCommandRegistry",
    "create_diff_panel",
    "get_console",
    "get_git_branch",
    "get_repo_name",
    "print_diff_panel",
    "print_startup_banner",
    "registry",
    "render_status_toolbar",
    "run_repl",
    "start_repl",
]


def __getattr__(name: str) -> Any:
    if name in ("SlashCommand", "SlashCommandRegistry", "registry"):
        import lathe.ui.commands as _cmds

        return getattr(_cmds, name)
    if name == "LatheCompleter":
        from lathe.ui.completer import LatheCompleter as _lc

        return _lc
    if name in ("run_repl", "start_repl"):
        import lathe.ui.repl as _repl

        return getattr(_repl, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
