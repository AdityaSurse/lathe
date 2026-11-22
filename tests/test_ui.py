"""Tests for lathe.ui: theme, banner, status bar, completer, slash commands, and REPL."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from rich.console import Console

from lathe import __version__
from lathe.config import LatheConfig, RoleConfig
from lathe.llm.types import StreamChunk, Usage
from lathe.ui.banner import print_startup_banner
from lathe.ui.commands import (
    SlashCommand,
    SlashCommandRegistry,
    handle_clear,
    handle_exit,
    handle_help,
    handle_mode,
    handle_model,
    handle_tokens,
)
from lathe.ui.completer import LatheCompleter
from lathe.ui.repl import _stream_chat_turn, get_history_file_path
from lathe.ui.status import (
    SessionStats,
    get_git_branch,
    get_repo_name,
    render_status_toolbar,
)
from lathe.ui.theme import LATHE_THEME, PRIMARY, SECONDARY, get_console


def test_theme_and_console() -> None:
    """Console must be configured with Lathe palette theme."""
    console = get_console()
    assert console is not None
    assert "lathe.primary" in LATHE_THEME.styles
    assert PRIMARY == "#38bdf8"
    assert SECONDARY == "#818cf8"


def test_startup_banner() -> None:
    """Startup banner must print ASCII logo, version, and active models."""
    console = Console(record=True)
    cfg = LatheConfig(
        roles={
            "coder": RoleConfig(backend="ollama", model="test-coder"),
            "planner": RoleConfig(backend="hf", model="test-planner"),
            "router": RoleConfig(backend="ollama", model="test-router"),
        }
    )
    print_startup_banner(cfg, console=console)
    output = console.export_text()

    assert "Turn prompts into code. Locally." in output
    assert f"Lathe v{__version__}" in output
    assert "test-coder" in output
    assert "test-planner" in output
    assert "test-router" in output
    assert "/help" in output


def test_session_stats_and_status_toolbar() -> None:
    """SessionStats must accumulate token counts and render formatted HTML toolbar."""
    stats = SessionStats()
    assert stats.total_tokens == 0

    stats.add_usage(Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15))
    stats.add_usage(Usage(prompt_tokens=20, completion_tokens=10, total_tokens=30))

    assert stats.prompt_tokens == 30
    assert stats.completion_tokens == 15
    assert stats.total_tokens == 45
    assert stats.request_count == 2

    cfg = LatheConfig(
        roles={
            "coder": RoleConfig(backend="ollama", model="hf.co/bartowski/Qwen2.5-Coder:Q4_K_M"),
            "planner": RoleConfig(backend="hf", model="deepseek-ai/DeepSeek-R1"),
        }
    )
    toolbar = render_status_toolbar(cfg, stats)
    html_text = toolbar.value
    assert "repo:" in html_text
    assert "git:" in html_text
    assert "mode:" in html_text
    assert "coder:" in html_text
    assert "45" in html_text


def test_git_branch_and_repo_name(tmp_path: Path) -> None:
    """get_git_branch and get_repo_name must identify repo details."""
    repo_name = get_repo_name(tmp_path)
    assert repo_name == tmp_path.name

    # tmp_path has no git, should report no-git
    branch = get_git_branch(tmp_path)
    assert branch in ("no-git", "detached", "main", "master")


def test_completer_slash_commands() -> None:
    """LatheCompleter must suggest registered slash commands."""
    completer = LatheCompleter()
    doc = Document(text="/m", cursor_position=2)
    completions = list(completer.get_completions(doc, CompleteEvent()))

    texts = [c.text for c in completions]
    assert "/model" in texts
    assert "/mode" in texts
    assert "/help" not in texts


def test_completer_at_file_paths(tmp_path: Path) -> None:
    """LatheCompleter must autocomplete file and directory paths with @ prefix."""
    (tmp_path / "main.py").write_text("print(1)")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("console.log(1)")

    completer = LatheCompleter(workspace_root=tmp_path)

    # Autocomplete @m -> @main.py
    doc1 = Document(text="check @m", cursor_position=8)
    res1 = list(completer.get_completions(doc1, CompleteEvent()))
    assert len(res1) == 1
    assert res1[0].text == "@main.py"

    # Autocomplete @src/ -> @src/index.ts
    doc2 = Document(text="open @src/", cursor_position=10)
    res2 = list(completer.get_completions(doc2, CompleteEvent()))
    assert len(res2) == 1
    assert res2[0].text == "@src/index.ts"


def test_slash_command_registry() -> None:
    """SlashCommandRegistry must register, list, and dispatch commands."""
    reg = SlashCommandRegistry()
    mock_handler = MagicMock(return_value=True)
    cmd = SlashCommand(
        name="/test",
        description="Test command",
        usage="/test [arg]",
        handler=mock_handler,
    )
    reg.register(cmd)

    assert reg.get("/test") == cmd
    assert reg.get("/TEST") == cmd
    assert len(reg.list_commands()) == 1

    cfg = LatheConfig()
    stats = SessionStats()
    console = Console()

    res = reg.execute("/test arg1 arg2", cfg, stats, console)
    assert res is True
    mock_handler.assert_called_once_with(["arg1", "arg2"], cfg, stats, console)


def test_builtin_slash_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test built-in slash command handlers: help, model, mode, clear, tokens, exit."""
    fake_toml = tmp_path / "lathe.toml"
    fake_toml.write_text("[roles.coder]\nbackend = 'ollama'\nmodel = 'old'\n")
    monkeypatch.setattr("lathe.ui.commands.get_project_config_path", lambda: fake_toml)

    cfg = LatheConfig()
    stats = SessionStats(prompt_tokens=100, completion_tokens=50, total_tokens=150, request_count=3)
    console = Console(record=True)

    # /help
    assert handle_help([], cfg, stats, console) is True
    assert "Lathe Slash Commands" in console.export_text()

    # /mode
    assert handle_mode(["dual"], cfg, stats, console) is True
    assert cfg.settings.mode == "dual"
    assert handle_mode(["single"], cfg, stats, console) is True
    assert cfg.settings.mode == "single"

    # /model
    assert handle_model(["coder", "custom-coder:7b"], cfg, stats, console) is True
    assert cfg.roles.coder.model == "custom-coder:7b"

    # /clear
    assert handle_clear([], cfg, stats, console) is True

    # /tokens
    assert handle_tokens([], cfg, stats, console) is True
    assert "Session Token Consumption" in console.export_text()

    # /exit returns False to break REPL loop
    assert handle_exit([], cfg, stats, console) is False


@pytest.mark.asyncio
async def test_repl_stream_chat_turn() -> None:
    """_stream_chat_turn must stream deltas, accumulate text, and record token usage."""

    class MockClient:
        def __init__(self) -> None:
            self.role_config = RoleConfig(backend="ollama", model="test-coder")

        async def chat(self, messages: Any, stream: bool = True) -> Any:
            yield StreamChunk(delta="Hello ", done=False)
            yield StreamChunk(delta="world!", done=False)
            yield StreamChunk(
                done=True,
                finish_reason="stop",
                usage=Usage(prompt_tokens=5, completion_tokens=2, total_tokens=7),
            )

    client = MockClient()
    stats = SessionStats()
    console = Console(record=True)
    messages = []

    result = await _stream_chat_turn(client, messages, stats, console)
    assert result == "Hello world!"
    assert stats.total_tokens == 7
    assert stats.request_count == 1
    assert "test-coder" in console.export_text()


def test_history_file_path() -> None:
    """get_history_file_path must point to ~/.config/lathe/history."""
    path = get_history_file_path()
    assert path.name == "history"
    assert path.parent.name == "lathe"
