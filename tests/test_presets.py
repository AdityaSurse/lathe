"""Unit tests for model presets, Gemma compatibility, and thinking block stripping."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lathe.cli import app
from lathe.config import LatheConfig
from lathe.llm.types import Message
from lathe.models.presets import (
    apply_preset_to_toml_file,
    format_messages_with_system_fallback,
    generate_preset_toml,
    get_preset,
    list_presets,
    strip_thinking_blocks,
)
from lathe.orchestrator.dual import extract_json_block

runner = CliRunner()


def test_preset_retrieval_and_parsing() -> None:
    """Test preset retrieval by name including case insensitivity and error handling."""
    qwen = get_preset("qwen")
    assert qwen.name == "qwen"
    assert "Qwen2.5-Coder-7B" in qwen.coder.model
    assert "DeepSeek-R1" in qwen.planner.model

    gemma = get_preset("GEMMA")
    assert gemma.name == "gemma"
    assert gemma.coder.model == "gemma4:e4b"
    assert gemma.router.model == "gemma4:e2b"
    assert gemma.planner.model == "gemma4:e4b"

    mixed = get_preset("Mixed")
    assert mixed.name == "mixed"
    assert "Qwen2.5-Coder-7B" in mixed.coder.model
    assert mixed.router.model == "gemma4:e2b"

    with pytest.raises(ValueError, match="Unknown model preset"):
        get_preset("nonexistent_preset")


def test_list_presets() -> None:
    """Test listing all presets returns expected keys."""
    all_presets = list_presets()
    names = [p.name for p in all_presets]
    assert "qwen" in names
    assert "gemma" in names
    assert "mixed" in names
    assert len(all_presets) == 3


def test_strip_thinking_blocks() -> None:
    """Test stripping <think> and <thought> tags from reasoning model outputs."""
    raw = (
        "<think>\n"
        "Need to analyze dependencies and create a 3-step plan.\n"
        "Let's see: file is src/main.py.\n"
        "</think>\n"
        '```json\n{"goal": "Build feature", "steps": []}\n```'
    )
    cleaned = strip_thinking_blocks(raw)
    assert "<think>" not in cleaned
    assert "</think>" not in cleaned
    assert '{"goal": "Build feature"' in cleaned

    # Test extract_json_block integrates stripping
    extracted = extract_json_block(raw)
    assert extracted.startswith("{")
    assert extracted.endswith("}")

    # Case-insensitive thinking tags
    raw_upper = '<THINK>Thinking deeply...</THINK>{"result": 42}'
    assert strip_thinking_blocks(raw_upper) == '{"result": 42}'


def test_system_prompt_fallback() -> None:
    """Test system prompt serialization with and without system role support."""
    messages = [
        Message(role="system", content="You are a helpful coding assistant."),
        Message(role="user", content="Refactor the auth handler."),
    ]

    # Native system role supported
    native = format_messages_with_system_fallback(messages, support_system=True)
    assert len(native) == 2
    assert native[0]["role"] == "system"
    assert native[0]["content"] == "You are a helpful coding assistant."
    assert native[1]["role"] == "user"

    # Fallback when system role is not supported (prepended to first user message)
    fallback = format_messages_with_system_fallback(messages, support_system=False)
    assert len(fallback) == 1
    assert fallback[0]["role"] == "user"
    assert "You are a helpful coding assistant." in fallback[0]["content"]
    assert "Refactor the auth handler." in fallback[0]["content"]

    # Multiple system messages combined
    multi_sys = [
        Message(role="system", content="Rule 1."),
        Message(role="system", content="Rule 2."),
        Message(role="user", content="Hello"),
    ]
    fb_multi = format_messages_with_system_fallback(multi_sys, support_system=False)
    assert len(fb_multi) == 1
    assert fb_multi[0]["content"] == "Rule 1.\n\nRule 2.\n\nHello"


def test_generate_preset_toml_and_validation() -> None:
    """Test that generated TOML is valid according to LatheConfig schema."""
    for p_name in ("qwen", "gemma", "mixed"):
        preset = get_preset(p_name)
        toml_str = generate_preset_toml(preset)
        data = tomllib.loads(toml_str)
        cfg = LatheConfig.model_validate(data)
        assert cfg.roles.planner.model == preset.planner.model
        assert cfg.roles.coder.model == preset.coder.model
        assert cfg.roles.router.model == preset.router.model


def test_apply_preset_to_toml_file(tmp_path: Path) -> None:
    """Test writing and updating preset in lathe.toml."""
    target = tmp_path / "lathe.toml"
    gemma = get_preset("gemma")

    # Initial write to new file
    apply_preset_to_toml_file(gemma, target)
    assert target.exists()
    cfg1 = LatheConfig.model_validate(tomllib.loads(target.read_text(encoding="utf-8")))
    assert cfg1.roles.coder.model == "gemma4:e4b"

    # Update to qwen preset
    qwen = get_preset("qwen")
    apply_preset_to_toml_file(qwen, target)
    cfg2 = LatheConfig.model_validate(tomllib.loads(target.read_text(encoding="utf-8")))
    assert "Qwen2.5-Coder-7B" in cfg2.roles.coder.model


def test_cli_models_presets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 'lathe models presets' output formatting."""

    async def mock_local_models() -> list[dict[str, str]]:
        return [
            {"name": "hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M"},
            {"name": "gemma4:e2b"},
        ]

    monkeypatch.setattr("lathe.models.cli.get_local_ollama_models", mock_local_models)
    result = runner.invoke(app, ["models", "presets"])
    assert result.exit_code == 0
    assert "Lathe Model Presets" in result.stdout
    assert "qwen" in result.stdout
    assert "gemma" in result.stdout
    assert "mixed" in result.stdout


def test_cli_config_init_preset(tmp_path: Path) -> None:
    """Test 'lathe config init --preset gemma'."""
    target = tmp_path / "lathe.toml"
    result = runner.invoke(app, ["config", "init", "--path", str(target), "--preset", "gemma"])
    assert result.exit_code == 0
    assert "with preset 'gemma'" in result.stdout

    cfg = LatheConfig.model_validate(tomllib.loads(target.read_text(encoding="utf-8")))
    assert cfg.roles.coder.model == "gemma4:e4b"
    assert cfg.roles.router.model == "gemma4:e2b"
