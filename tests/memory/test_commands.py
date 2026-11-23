"""Unit tests for custom slash command markdown loader and $ARGS substitution."""

from __future__ import annotations

from pathlib import Path

from lathe.memory.commands import CustomCommand, CustomCommandManager


def test_custom_command_render_args():
    """$ARGS is replaced with full argument string."""
    cmd = CustomCommand(
        name="fix-issue",
        path="/dummy.md",
        template="Please investigate issue #$ARGS and fix tests.",
    )
    rendered = cmd.render(["42", "--verbose"])
    assert rendered == "Please investigate issue #42 --verbose and fix tests."


def test_custom_command_render_positional():
    """$1, $2, etc. are substituted with positional arguments."""
    cmd = CustomCommand(
        name="review-pr",
        path="/dummy.md",
        template="Review PR $1 with focus on $2.",
    )
    rendered = cmd.render(["108", "security"])
    assert rendered == "Review PR 108 with focus on security."


def test_load_and_save_custom_command(tmp_path: Path):
    """CustomCommandManager saves and loads markdown commands."""
    mgr = CustomCommandManager(tmp_path)
    saved_path = mgr.save_command(
        name="deploy",
        template="# Automated Deploy\nDeploy application to $ARGS environment.",
    )
    assert saved_path.exists()
    assert saved_path.name == "deploy.md"

    commands = mgr.load_commands()
    assert "deploy" in commands
    assert commands["deploy"].description == "Automated Deploy"

    rendered = mgr.render_prompt("deploy", ["production"])
    assert rendered == "# Automated Deploy\nDeploy application to production environment."

    assert mgr.delete_command("deploy") is True
    assert mgr.get_command("deploy") is None
