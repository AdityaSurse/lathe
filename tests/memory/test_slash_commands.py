"""Unit tests for /init and /remember slash command execution."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from lathe.config import load_config
from lathe.memory.commands import CustomCommandManager
from lathe.ui.commands import (
    get_pending_prompt,
    handle_init,
    handle_remember,
    registry,
)
from lathe.ui.status import SessionStats


def test_handle_init_slash_command(tmp_path: Path, monkeypatch):
    """handle_init explores repo and writes LATHE.md."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")

    cfg = load_config(require_secrets=False)
    stats = SessionStats()
    console = Console()

    # Run /init
    ok = handle_init(["--force"], cfg, stats, console)
    assert ok is True

    lathe_md = tmp_path / "LATHE.md"
    assert lathe_md.exists()
    assert "# Project Instructions (LATHE.md)" in lathe_md.read_text(encoding="utf-8")


def test_handle_remember_slash_command(tmp_path: Path, monkeypatch):
    """handle_remember appends notes to LATHE.md."""
    monkeypatch.chdir(tmp_path)

    cfg = load_config(require_secrets=False)
    stats = SessionStats()
    console = Console()

    ok = handle_remember(["Always", "use", "snake_case"], cfg, stats, console)
    assert ok is True

    lathe_md = tmp_path / "LATHE.md"
    assert lathe_md.exists()
    content = lathe_md.read_text(encoding="utf-8")
    assert "Always use snake_case" in content


def test_custom_command_sets_pending_prompt(tmp_path: Path, monkeypatch):
    """Invoking a custom command sets pending prompt for agent REPL."""
    monkeypatch.chdir(tmp_path)
    mgr = CustomCommandManager(tmp_path)
    mgr.save_command("audit", "Run security audit on $ARGS.")

    cfg = load_config(require_secrets=False)
    stats = SessionStats()
    console = Console()

    ok = registry.execute("/audit dependencies", cfg, stats, console)
    assert ok is True

    pending = get_pending_prompt()
    assert pending == "Run security audit on dependencies."
