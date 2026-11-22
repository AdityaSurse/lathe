"""Tests for Lathe configuration system: loading, precedence, validation, and CLI."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lathe.cli import app
from lathe.config import (
    ConfigError,
    LatheConfig,
    load_config,
    set_config_value,
)

runner = CliRunner()


def test_default_config() -> None:
    """Verify sensible defaults for all roles and settings."""
    cfg = LatheConfig()

    # Coder defaults to local 7B Qwen coder
    assert cfg.roles.coder.backend == "ollama"
    assert "Qwen2.5-Coder-7B" in cfg.roles.coder.model
    assert cfg.roles.coder.temperature == 0.2
    assert cfg.roles.coder.context_window == 32768

    # Router defaults to local 1.5B
    assert cfg.roles.router.backend == "ollama"
    assert "1.5B" in cfg.roles.router.model
    assert cfg.roles.router.temperature == 0.0

    # Planner defaults to HF reasoning model placeholder
    assert cfg.roles.planner.backend == "hf"
    assert "DeepSeek-R1" in cfg.roles.planner.model
    assert cfg.roles.planner.context_window == 65536

    # Reviewer defaults to planner when not explicitly specified
    assert cfg.roles.reviewer is None
    assert cfg.get_reviewer().model == cfg.roles.planner.model

    # Settings
    assert cfg.settings.mode in ("auto", "dual")
    assert cfg.settings.max_agent_steps in (10, 25)
    assert cfg.settings.auto_approve_reads is True
    assert "rm -rf /" in cfg.settings.blocked_commands


def test_config_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify two-level TOML precedence: project overrides global."""
    # Ensure a dummy HF token is set so secret validation succeeds
    monkeypatch.setenv("HF_TOKEN", "hf_test_secret_token_12345")

    global_file = tmp_path / "global_lathe.toml"
    global_file.write_text(
        """
[settings]
max_agent_steps = 25
theme = "global-theme"

[roles.coder]
backend = "ollama"
model = "global-coder-model"
temperature = 0.5
""",
        encoding="utf-8",
    )

    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    project_file = project_dir / "lathe.toml"
    project_file.write_text(
        """
[settings]
theme = "project-theme"

[roles.coder]
model = "project-coder-model"
""",
        encoding="utf-8",
    )

    loaded = load_config(
        project_dir=project_dir,
        global_path=global_file,
        require_secrets=True,
    )

    # Project overrides global
    assert loaded.settings.theme == "project-theme"
    assert loaded.roles.coder.model == "project-coder-model"

    # Global non-overridden value persists
    assert loaded.settings.max_agent_steps == 25
    assert loaded.roles.coder.temperature == 0.5

    # Defaults persist when neither sets them
    assert loaded.roles.coder.backend == "ollama"
    assert loaded.roles.router.model == "hf.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF:Q4_K_M"


def test_missing_token_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that using HF backend without HF_TOKEN raises a friendly ConfigError."""
    # Clear any HF tokens from environment
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)

    project_file = tmp_path / "lathe.toml"
    project_file.write_text(
        """
[roles.planner]
backend = "hf"
model = "deepseek-ai/DeepSeek-R1"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_config(
            project_dir=tmp_path,
            global_path=tmp_path / "nonexistent.toml",
            require_secrets=True,
        )

    err = exc_info.value
    assert "HF_TOKEN" in err.message
    assert "roles.planner.backend" in err.key


def test_invalid_backend_error(tmp_path: Path) -> None:
    """Verify that an invalid backend string raises a friendly ConfigError with choices."""
    project_file = tmp_path / "lathe.toml"
    project_file.write_text(
        """
[roles.coder]
backend = "unsupported_runtime"
model = "some-model"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_config(
            project_dir=tmp_path,
            global_path=tmp_path / "nonexistent.toml",
            require_secrets=False,
        )

    err = exc_info.value
    assert "roles.coder.backend" in err.key
    assert "ollama" in err.message
    assert "hf" in err.message
    assert "openai_compat" in err.message


def test_secret_in_toml_forbidden(tmp_path: Path) -> None:
    """Verify that attempting to place an API token in a TOML file is strictly rejected."""
    project_file = tmp_path / "lathe.toml"
    project_file.write_text(
        """
[roles.planner]
backend = "hf"
model = "deepseek-ai/DeepSeek-R1"
hf_token = "hf_forbidden_secret"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_config(
            project_dir=tmp_path,
            global_path=tmp_path / "nonexistent.toml",
            require_secrets=False,
        )

    err = exc_info.value
    assert "Secret" in err.message
    assert "roles.planner.hf_token" in err.key


def test_set_config_value(tmp_path: Path) -> None:
    """Verify programmatic setting of dotted keys in lathe.toml."""
    project_file = tmp_path / "lathe.toml"

    # Set model on coder
    cfg1 = set_config_value("roles.coder.model", "qwen2.5-coder:14b", project_file)
    assert cfg1.roles.coder.model == "qwen2.5-coder:14b"
    assert project_file.exists()

    # Set temperature (float coercion)
    cfg2 = set_config_value("roles.coder.temperature", "0.75", project_file)
    assert cfg2.roles.coder.temperature == 0.75

    # Invalid backend is rejected
    with pytest.raises(ConfigError) as exc_info:
        set_config_value("roles.coder.backend", "fake_engine", project_file)
    assert "roles.coder.backend" in exc_info.value.key


def test_cli_config_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test `lathe config init`, `lathe config show`, and `lathe config set` commands."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HF_TOKEN", "hf_mock_secret_for_testing_123456")

    # 1. lathe config init
    res_init = runner.invoke(app, ["config", "init"])
    assert res_init.exit_code == 0
    assert "Initialized configuration file" in res_init.stdout
    assert (tmp_path / "lathe.toml").exists()

    # Re-init without --force should fail
    res_init_dup = runner.invoke(app, ["config", "init"])
    assert res_init_dup.exit_code == 1
    assert "already exists" in res_init_dup.stdout

    # 2. lathe config show
    res_show = runner.invoke(app, ["config", "show"])
    assert res_show.exit_code == 0
    assert "Lathe Configuration" in res_show.stdout
    assert "coder" in res_show.stdout
    assert "masked: hf_m****" in res_show.stdout  # Secret is masked

    # 3. lathe config set
    res_set = runner.invoke(app, ["config", "set", "roles.coder.model", "qwen2.5-coder:32b"])
    assert res_set.exit_code == 0
    assert "Updated 'roles.coder.model'" in res_set.stdout

    # Verify change reflected in show
    res_show2 = runner.invoke(app, ["config", "show"])
    assert "qwen2.5-coder:32b" in res_show2.stdout
