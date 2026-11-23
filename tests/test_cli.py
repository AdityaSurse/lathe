"""Tests for the lathe CLI entry point and commands."""

import pytest
from typer.testing import CliRunner

from lathe import __version__
from lathe.cli import app

runner = CliRunner()


def test_lathe_version() -> None:
    """Verify that `lathe --version` displays the current version and exits with code 0."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "lathe version" in result.stdout
    assert __version__ in result.stdout


@pytest.mark.slow
def test_lathe_doctor() -> None:
    """Verify that `lathe doctor` runs diagnostics without unhandled exceptions."""
    result = runner.invoke(app, ["doctor"], input="y\n")
    assert result.exit_code == 0
    assert "Python" in result.stdout
    assert "Git" in result.stdout
    assert "Ollama Service" in result.stdout
    assert "HF_TOKEN" in result.stdout


def test_lathe_tools_command() -> None:
    """Verify that `lathe tools` and `lathe tool` display registered workspace tools."""
    res_tools = runner.invoke(app, ["tools"], input="y\n")
    assert res_tools.exit_code == 0
    assert "Lathe Workspace Tools" in res_tools.stdout
    assert "edit_file" in res_tools.stdout
    assert "read_file" in res_tools.stdout
    assert "git_status" in res_tools.stdout
    assert "git_commit" in res_tools.stdout

    res_tool = runner.invoke(app, ["tool"], input="y\n")
    assert res_tool.exit_code == 0
    assert "Lathe Workspace Tools" in res_tool.stdout

    res_inspect = runner.invoke(app, ["tools", "edit_file"], input="y\n")
    assert res_inspect.exit_code == 0
    assert "Tool: edit_file" in res_inspect.stdout
    assert "Parameters Schema:" in res_inspect.stdout

    res_shell = runner.invoke(app, ["tools", "run_shell"], input="y\n")
    assert res_shell.exit_code == 0
    assert "Tool: run_shell" in res_shell.stdout
    assert "Risk Level: execute" in res_shell.stdout


def test_lathe_yolo_warning_cli() -> None:
    """Verify that --yolo emits the security warning panel."""
    res = runner.invoke(app, ["--yolo", "tools"])
    assert res.exit_code == 0
    assert "WARNING: YOLO mode active" in res.stdout


def test_lathe_dual_option_in_cli_help() -> None:
    """Verify that --dual is listed in lathe CLI help."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "--dual" in res.stdout
    assert "--auto" in res.stdout
    assert "--yolo" in res.stdout
