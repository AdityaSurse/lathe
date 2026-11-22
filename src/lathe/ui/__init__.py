"""User interface package providing Rich themes, status bars, slash commands, and REPL."""

from lathe.ui.banner import print_startup_banner
from lathe.ui.commands import SlashCommand, SlashCommandRegistry, registry
from lathe.ui.completer import LatheCompleter
from lathe.ui.repl import run_repl, start_repl
from lathe.ui.status import SessionStats, get_git_branch, get_repo_name, render_status_toolbar
from lathe.ui.theme import LATHE_THEME, get_console

__all__ = [
    "LATHE_THEME",
    "LatheCompleter",
    "SessionStats",
    "SlashCommand",
    "SlashCommandRegistry",
    "get_console",
    "get_git_branch",
    "get_repo_name",
    "print_startup_banner",
    "registry",
    "render_status_toolbar",
    "run_repl",
    "start_repl",
]
