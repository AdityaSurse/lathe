"""Unit tests for merge CLI and wizard integration."""

from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from lathe.cli import app
from lathe.merge.models import ModelArchitectureInfo
from lathe.merge.wizard import run_merge_wizard

runner = CliRunner()


def test_merge_help():
    """Verify lathe merge help renders correctly."""
    result = runner.invoke(app, ["merge", "--help"])
    assert result.exit_code == 0
    assert "Model merging with mergekit" in result.output
    assert "--colab" in result.output
    assert "--preset" in result.output


def test_merge_wizard_with_preset_colab(tmp_path: Path, monkeypatch):
    """Merge wizard with --colab flag generates Colab notebook."""
    monkeypatch.chdir(tmp_path)

    # Mock fetch_model_info so we don't query real network in tests
    fake_info = ModelArchitectureInfo(
        repo_id="Qwen/Qwen2.5-Coder-1.5B",
        model_type="qwen2",
        hidden_size=1536,
        num_hidden_layers=28,
        vocab_size=151936,
        tokenizer_class="Qwen2TokenizerFast",
        estimated_params=1_540_000_000,
    )
    monkeypatch.setattr("lathe.merge.wizard.fetch_model_info", lambda _: fake_info)

    run_merge_wizard(
        colab=True,
        name="test-preset-colab",
        preset=True,
    )

    colab_file = tmp_path / "merges" / "test-preset-colab" / "merge_test-preset-colab.ipynb"
    assert colab_file.exists()
    assert (tmp_path / "merges" / "test-preset-colab" / "config.yaml").exists()
    assert (tmp_path / "merges" / "test-preset-colab" / "README.md").exists()


def test_merge_push_cli(tmp_path: Path, monkeypatch):
    """Test lathe merge push CLI invocation."""
    monkeypatch.chdir(tmp_path)
    merge_dir = tmp_path / "merges" / "my-model"
    merge_dir.mkdir(parents=True)
    (merge_dir / "config.yaml").write_text("merge_method: slerp", encoding="utf-8")

    mock_push = MagicMock(return_value="https://huggingface.co/user/my-model")
    monkeypatch.setattr("lathe.merge.hub.push_to_hub", mock_push)

    result = runner.invoke(app, ["merge", "push", "my-model", "--yes"])
    assert result.exit_code == 0
    mock_push.assert_called_once()


def test_merge_positional_name_argument(tmp_path: Path, monkeypatch):
    """Positional name argument (e.g. lathe merge qwen-1.5b --colab) routes properly."""
    monkeypatch.chdir(tmp_path)

    fake_info = ModelArchitectureInfo(
        repo_id="Qwen/Qwen2.5-Coder-1.5B",
        model_type="qwen2",
        hidden_size=1536,
        num_hidden_layers=28,
        vocab_size=151936,
        tokenizer_class="Qwen2TokenizerFast",
        estimated_params=1_540_000_000,
    )
    monkeypatch.setattr("lathe.merge.wizard.fetch_model_info", lambda _: fake_info)

    result = runner.invoke(app, ["merge", "qwen-1.5b", "--colab", "--preset"])
    assert result.exit_code == 0
    colab_file = tmp_path / "merges" / "qwen-1.5b" / "merge_qwen-1.5b.ipynb"
    assert colab_file.exists()
