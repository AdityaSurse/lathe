"""Tests for working tree checkpoints, isolated git refs, non-destructive undo, and restore."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from lathe.safety.checkpoints import (
    CHECKPOINT_REF_PREFIX,
    CheckpointManager,
    suggest_conventional_commit,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary initialized git repository with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Lathe Tester"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@lathe.ai"], cwd=repo, check=True)

    # Initial tracked file & commit
    (repo / "hello.txt").write_text("initial content\n", encoding="utf-8")
    subprocess.run(["git", "add", "hello.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=repo, check=True)

    return repo


def test_checkpoint_creation_uses_isolated_refs(git_repo: Path) -> None:
    """Verify checkpoints are saved under refs/lathe/checkpoints/<session>/<n>."""
    cm = CheckpointManager(git_repo, session_id="test_sess_01")
    assert cm.is_enabled is True

    ckpt = cm.create_checkpoint("First checkpoint")
    assert ckpt is not None
    assert ckpt.number == 1
    assert ckpt.ref == f"{CHECKPOINT_REF_PREFIX}/test_sess_01/1"
    assert ckpt.commit_sha != ""
    assert ckpt.tree_sha != ""

    # Verify ref exists in git repository
    proc = subprocess.run(
        ["git", "rev-parse", ckpt.ref],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == ckpt.commit_sha


def test_user_staged_changes_remain_untouched_by_checkpoint_and_undo(git_repo: Path) -> None:
    """CRITICAL: User's staged changes must remain untouched across checkpoints and undo."""
    # 1. User stages a file
    (git_repo / "user_staged.txt").write_text("user staged work\n", encoding="utf-8")
    subprocess.run(["git", "add", "user_staged.txt"], cwd=git_repo, check=True)

    status_before = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "A  user_staged.txt" in status_before

    # 2. Checkpoint taken before tool makes edits
    cm = CheckpointManager(git_repo, session_id="sess_undo_test")
    ckpt1 = cm.create_checkpoint("Before tool modification")
    assert ckpt1 is not None

    # Staged status must still be present immediately after checkpoint creation
    status_after_ckpt = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "A  user_staged.txt" in status_after_ckpt

    # 3. Tool modifies existing file and creates a new one
    (git_repo / "hello.txt").write_text("modified by tool\n", encoding="utf-8")
    (git_repo / "tool_created.txt").write_text("created by tool\n", encoding="utf-8")

    # 4. User triggers undo
    undone = cm.undo()
    assert undone is not None
    assert undone.number == 1

    # 5. Verify working tree was restored
    assert (git_repo / "hello.txt").read_text(encoding="utf-8") == "initial content\n"
    assert not (git_repo / "tool_created.txt").exists()

    # 6. Verify user's staged file is STILL safely staged in .git/index
    status_after_undo = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "A  user_staged.txt" in status_after_undo
    assert (git_repo / "user_staged.txt").read_text(encoding="utf-8") == "user staged work\n"


def test_restore_specific_checkpoint(git_repo: Path) -> None:
    """Verify restoring a specific historical checkpoint number."""
    cm = CheckpointManager(git_repo, session_id="sess_multi")

    # State 1
    (git_repo / "step.txt").write_text("step 1\n", encoding="utf-8")
    ckpt1 = cm.create_checkpoint("Step 1")
    assert ckpt1 is not None and ckpt1.number == 1

    # State 2
    (git_repo / "step.txt").write_text("step 2\n", encoding="utf-8")
    (git_repo / "extra.txt").write_text("extra file\n", encoding="utf-8")
    ckpt2 = cm.create_checkpoint("Step 2")
    assert ckpt2 is not None and ckpt2.number == 2

    # State 3
    (git_repo / "step.txt").write_text("step 3\n", encoding="utf-8")

    # Restore to Checkpoint 1
    success = cm.restore(1)
    assert success is True
    assert (git_repo / "step.txt").read_text(encoding="utf-8") == "step 1\n"
    assert not (git_repo / "extra.txt").exists()

    # Restore back to Checkpoint 2
    success2 = cm.restore(2)
    assert success2 is True
    assert (git_repo / "step.txt").read_text(encoding="utf-8") == "step 2\n"
    assert (git_repo / "extra.txt").read_text(encoding="utf-8") == "extra file\n"


def test_session_diff_generation(git_repo: Path) -> None:
    """Verify get_session_diff returns unified diff relative to first checkpoint."""
    cm = CheckpointManager(git_repo, session_id="sess_diff")
    cm.create_checkpoint("Initial session snapshot")

    # Make modifications
    (git_repo / "hello.txt").write_text("new content for diff test\n", encoding="utf-8")
    (git_repo / "added.txt").write_text("added file line\n", encoding="utf-8")

    diff = cm.get_session_diff()
    assert "-initial content" in diff
    assert "+new content for diff test" in diff
    assert "+added file line" in diff


def test_non_git_repository_handling(tmp_path: Path) -> None:
    """Non-git folder disables checkpoints gracefully with warning and returns None."""
    non_repo = tmp_path / "not_git"
    non_repo.mkdir()

    cm = CheckpointManager(non_repo, prompt_init=False)
    assert cm.is_enabled is False
    assert cm.create_checkpoint("Test") is None
    assert cm.undo() is None
    assert cm.restore(1) is False
    assert cm.get_session_diff() == ""


@pytest.mark.asyncio
async def test_suggest_conventional_commit_with_mock_client() -> None:
    """Verify Conventional Commits message generation from diff."""
    from lathe.llm.types import StreamChunk

    class MockClient:
        async def chat(self, messages: list[Any], stream: bool = False):
            yield StreamChunk(delta="feat(auth): implement JWT token verification")

    mock_client = MockClient()
    diff = "--- a/auth.py\n+++ b/auth.py\n@@ -1 +1,2 @@\n+def verify_jwt(): pass\n"
    msg = await suggest_conventional_commit(diff, mock_client)
    assert msg == "feat(auth): implement JWT token verification"
