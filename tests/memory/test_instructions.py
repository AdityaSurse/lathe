"""Unit tests for LATHE.md project instructions loader and modifier."""

from __future__ import annotations

from pathlib import Path

import pytest

from lathe.config import RoleConfig
from lathe.llm.base import LLMClient
from lathe.llm.types import StreamChunk
from lathe.memory.instructions import (
    append_to_lathe_md,
    explore_repository,
    generate_initial_lathe_md,
    load_project_instructions,
)


class FakeInstructionLLM(LLMClient):
    """Deterministic LLM client returning formatted LATHE.md."""

    def __init__(self, response_text: str) -> None:
        super().__init__(
            role_config=RoleConfig(
                backend="ollama",
                model="fake-qwen",
                temperature=0.0,
                max_tokens=2048,
            )
        )
        self.response_text = response_text

    async def chat(self, messages, tools=None, stream=True):
        yield StreamChunk(delta=self.response_text, done=True)


def test_load_project_instructions_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Returns empty string when neither local nor global LATHE.md exists."""
    fake_global = tmp_path / "global_missing" / "LATHE.md"
    monkeypatch.setattr("lathe.memory.instructions.get_global_lathe_md_path", lambda: fake_global)
    result = load_project_instructions(tmp_path)
    assert result == ""


def test_load_project_instructions_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Loads and formats local LATHE.md if present."""
    fake_global = tmp_path / "global_missing" / "LATHE.md"
    monkeypatch.setattr("lathe.memory.instructions.get_global_lathe_md_path", lambda: fake_global)
    local_md = tmp_path / "LATHE.md"
    local_md.write_text("## Rule 1\nAlways write tests first.", encoding="utf-8")

    result = load_project_instructions(tmp_path)
    assert "Always write tests first." in result
    assert "Project Instructions (LATHE.md)" in result


def test_load_project_instructions_both(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Loads and merges both global and local instructions."""
    global_dir = tmp_path / "config"
    global_dir.mkdir(parents=True, exist_ok=True)
    global_md = global_dir / "LATHE.md"
    global_md.write_text("Global user rule: prefer concise code.", encoding="utf-8")

    local_md = tmp_path / "LATHE.md"
    local_md.write_text("Local rule: use Python 3.12.", encoding="utf-8")

    monkeypatch.setattr("lathe.memory.instructions.get_global_lathe_md_path", lambda: global_md)
    result = load_project_instructions(tmp_path)

    assert "Global User Guidelines" in result
    assert "prefer concise code" in result
    assert "Local rule: use Python 3.12." in result


def test_append_to_lathe_md_creates_new_file(tmp_path: Path):
    """append_to_lathe_md creates LATHE.md with ## Notes if file is missing."""
    target = tmp_path / "workspace"
    target.mkdir()

    path = append_to_lathe_md("Use strict typing everywhere.", workspace_root=target)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "## Notes" in content
    assert "- Use strict typing everywhere." in content


def test_append_to_lathe_md_existing_notes(tmp_path: Path):
    """append_to_lathe_md appends bullet under existing ## Notes section."""
    target = tmp_path / "LATHE.md"
    target.write_text(
        "# My Project\n\n## Tech Stack\nPython\n\n## Notes\n- Old note.\n\n## Other\nSomething.",
        encoding="utf-8",
    )

    path = append_to_lathe_md("New important fact.", workspace_root=tmp_path)
    content = path.read_text(encoding="utf-8")
    assert "- Old note." in content
    assert "- New important fact." in content
    assert "## Other" in content


def test_explore_repository(tmp_path: Path):
    """explore_repository extracts key files and languages."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")

    summary = explore_repository(tmp_path)
    assert "pyproject.toml" in str(summary["key_files"])
    assert "Python" in summary["languages"]


def test_generate_initial_lathe_md_fallback(tmp_path: Path):
    """Deterministic fallback creates structured LATHE.md."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test-pkg'\n", encoding="utf-8")

    content = generate_initial_lathe_md(workspace_root=tmp_path)
    assert "# Project Instructions (LATHE.md)" in content
    assert "## Tech Stack" in content
    assert "## How to Run" in content
    assert "## How to Test" in content
    assert "## Code Conventions" in content
    assert "## Notes" in content


def test_generate_initial_lathe_md_with_llm(tmp_path: Path):
    """LLM generation uses model client output."""
    mock_md = (
        "# Project Instructions (LATHE.md)\n\n"
        "## Tech Stack\n- Python & FastAPI\n\n"
        "## How to Run\n- uvicorn main:app\n\n"
        "## How to Test\n- pytest\n\n"
        "## Code Conventions\n- Ruff & Black\n\n"
        "## Notes\n- LLM generated note\n"
    )
    fake_client = FakeInstructionLLM(mock_md)
    content = generate_initial_lathe_md(workspace_root=tmp_path, client=fake_client)
    assert "Python & FastAPI" in content
    assert "LLM generated note" in content
