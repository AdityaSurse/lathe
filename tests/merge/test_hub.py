"""Unit tests for pushing merged models to Hugging Face Hub."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lathe.merge.hub import get_directory_size_bytes, push_to_hub


def test_get_directory_size_bytes(tmp_path: Path):
    """Accurately sum bytes across files in directory."""
    f1 = tmp_path / "model.safetensors"
    f1.write_bytes(b"x" * 1024)
    f2 = tmp_path / "README.md"
    f2.write_bytes(b"y" * 256)

    assert get_directory_size_bytes(tmp_path) == 1280


def test_push_to_hub_directory_not_found(tmp_path: Path):
    """Non-existent merge directory raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="does not exist"):
        push_to_hub("missing-merge", base_dir=tmp_path, interactive=False)


def test_push_to_hub_empty_directory(tmp_path: Path):
    """Empty merge directory raises ValueError."""
    merge_dir = tmp_path / "merges" / "empty-merge"
    merge_dir.mkdir(parents=True)

    with pytest.raises(ValueError, match="is empty"):
        push_to_hub("empty-merge", base_dir=tmp_path, interactive=False)


def test_push_to_hub_missing_token(tmp_path: Path, monkeypatch):
    """Missing Hugging Face token raises ValueError."""
    merge_dir = tmp_path / "merges" / "test-merge"
    merge_dir.mkdir(parents=True)
    (merge_dir / "config.yaml").write_text("dummy", encoding="utf-8")

    monkeypatch.setattr("lathe.merge.hub.get_hf_token", lambda: None)
    monkeypatch.setattr("huggingface_hub.get_token", lambda: None)

    with pytest.raises(ValueError, match="Hugging Face token not found"):
        push_to_hub("test-merge", base_dir=tmp_path, interactive=False)


def test_push_to_hub_success(tmp_path: Path, monkeypatch):
    """Successful upload creates private repo and calls upload_folder."""
    merge_dir = tmp_path / "merges" / "test-merge"
    merge_dir.mkdir(parents=True)
    (merge_dir / "config.yaml").write_text("merge_method: slerp", encoding="utf-8")

    mock_api = MagicMock()
    mock_api.whoami.return_value = {"name": "testuser"}
    monkeypatch.setattr("huggingface_hub.HfApi", lambda: mock_api)

    url = push_to_hub(
        "test-merge",
        repo_id="testuser/test-merge",
        token="hf_fake_token",
        base_dir=tmp_path,
        interactive=False,
    )

    assert url == "https://huggingface.co/testuser/test-merge"
    mock_api.create_repo.assert_called_once_with(
        repo_id="testuser/test-merge",
        token="hf_fake_token",
        private=True,
        exist_ok=True,
    )
    mock_api.upload_folder.assert_called_once()
