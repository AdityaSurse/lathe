"""Tests for the lathe CLI entry point and commands."""

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


def test_lathe_doctor() -> None:
    """Verify that `lathe doctor` runs diagnostics without unhandled exceptions."""
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Python" in result.stdout
    assert "Git" in result.stdout
    assert "Ollama Service" in result.stdout
    assert "HF_TOKEN" in result.stdout
