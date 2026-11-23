"""Unit tests for mergekit runner and model card generation."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lathe.merge.runner import (
    generate_model_card,
    is_mergekit_installed,
    run_mergekit,
    write_model_card,
)


def test_generate_model_card():
    """Model card includes markdown frontmatter, models, parameters, and GGUF guide."""
    card = generate_model_card(
        name="qwen-coder-instruct-merge",
        models=["Qwen/Qwen2.5-Coder-1.5B", "Qwen/Qwen2.5-1.5B-Instruct"],
        method="slerp",
        parameters={"t": 0.5},
        config_yaml="merge_method: slerp\nparameters:\n  t: 0.5\n",
    )

    # Frontmatter tags
    assert "tags:" in card
    assert "- mergekit" in card
    assert "- lathe" in card
    assert "Qwen/Qwen2.5-Coder-1.5B" in card
    assert "Qwen/Qwen2.5-1.5B-Instruct" in card
    # GGUF instructions
    assert "convert_hf_to_gguf.py" in card
    assert "llama-quantize" in card
    assert "ollama create" in card


def test_write_model_card(tmp_path: Path):
    """Writing model card to output directory."""
    path = write_model_card(
        output_dir=tmp_path,
        name="my-merge",
        models=["ModelA", "ModelB"],
        method="slerp",
        parameters={"t": 0.5},
        config_yaml="merge_method: slerp\n",
    )
    assert path.exists()
    assert path.name == "README.md"
    assert "# my-merge" in path.read_text(encoding="utf-8")


def test_run_mergekit_not_installed(tmp_path: Path, monkeypatch):
    """When mergekit-yaml is missing, informative error is raised."""
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert is_mergekit_installed() is False

    with pytest.raises(RuntimeError, match="mergekit is not installed"):
        run_mergekit(tmp_path / "config.yaml", tmp_path / "out")


def test_run_mergekit_success(tmp_path: Path, monkeypatch):
    """When mergekit-yaml runs successfully, stream lines and return 0."""
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/mergekit-yaml")

    mock_proc = MagicMock()
    mock_proc.stdout = ["Merging layer 0/28\n", "Merging layer 1/28\n"]
    mock_proc.wait.return_value = 0
    mock_proc.__enter__.return_value = mock_proc
    mock_proc.__exit__.return_value = None

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)

    ret = run_mergekit(tmp_path / "config.yaml", tmp_path / "out")
    assert ret == 0
