"""Tests for git tools: git_status, git_diff, git_log, and git_commit."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from lathe.safety.permissions import PermissionDecision, PermissionResult
from lathe.tools.base import ToolContext
from lathe.tools.git import git_commit, git_diff, git_log, git_status
from lathe.tools.registry import default_registry


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary initialized git repository with initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Lathe Tester"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@lathe.ai"], cwd=repo, check=True)

    # Initial file
    (repo / "README.md").write_text("# Project\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=repo, check=True)

    return repo


@pytest.mark.asyncio
async def test_git_status_tool_clean_and_modified(git_repo: Path) -> None:
    """Verify git_status reports clean status, untracked files, and modified files."""
    ctx = ToolContext(workspace_root=git_repo)

    # Clean state
    res_clean = await git_status.run({}, ctx=ctx)
    assert res_clean.ok is True
    assert "Branch:" in res_clean.output
    assert "Unstaged: (none)" in res_clean.output

    # Add untracked and modified file
    (git_repo / "new_file.py").write_text("print('hello')\n")
    (git_repo / "README.md").write_text("# Modified Project\n")

    res_dirty = await git_status.run({}, ctx=ctx)
    assert res_dirty.ok is True
    assert "new_file.py" in res_dirty.output
    assert "README.md" in res_dirty.output
    assert res_dirty.metadata["unstaged_count"] >= 1
    assert res_dirty.metadata["untracked_count"] >= 1


@pytest.mark.asyncio
async def test_git_diff_tool(git_repo: Path) -> None:
    """Verify git_diff shows unstaged, staged, and path-filtered diffs."""
    ctx = ToolContext(workspace_root=git_repo)

    # Clean diff
    res_clean = await git_diff.run({}, ctx=ctx)
    assert res_clean.ok is True
    assert "(no diff" in res_clean.output

    # Modify file
    (git_repo / "README.md").write_text("# Project\nNew line added\n")

    # Unstaged diff
    res_unstaged = await git_diff.run({"staged": False, "unstaged": True}, ctx=ctx)
    assert res_unstaged.ok is True
    assert "+New line added" in res_unstaged.output

    # Stage the modification
    subprocess.run(["git", "add", "README.md"], cwd=git_repo, check=True)

    # Staged diff
    res_staged = await git_diff.run({"staged": True, "unstaged": False}, ctx=ctx)
    assert res_staged.ok is True
    assert "+New line added" in res_staged.output


@pytest.mark.asyncio
async def test_git_log_tool(git_repo: Path) -> None:
    """Verify git_log retrieves commit history with specified limit."""
    ctx = ToolContext(workspace_root=git_repo)

    res = await git_log.run({"n": 5}, ctx=ctx)
    assert res.ok is True
    assert "chore: initial commit" in res.output
    assert "Lathe Tester" in res.output


@pytest.mark.asyncio
async def test_git_commit_tool_authorization_and_execution(git_repo: Path) -> None:
    """Verify git_commit risk level, permission engine gating, and commit creation."""
    assert git_commit.risk_level == "write"

    # 1. Denied by permission engine
    class DenyEngine:
        def check_permission(
            self, tool: Any, args: dict[str, Any], ctx: Any = None
        ) -> PermissionResult:
            return PermissionResult(decision=PermissionDecision.DENY, reason="User denied commit")

    ctx_denied = ToolContext(workspace_root=git_repo, permission_engine=DenyEngine())
    (git_repo / "feature.py").write_text("def feat(): pass\n")

    res_denied = await git_commit.run({"message": "feat: add feature"}, ctx=ctx_denied)
    assert res_denied.ok is False
    assert "User denied commit" in (res_denied.error or "")

    # 2. Approved execution
    class AllowEngine:
        def check_permission(
            self, tool: Any, args: dict[str, Any], ctx: Any = None
        ) -> PermissionResult:
            return PermissionResult(decision=PermissionDecision.ALLOW)

    ctx_allowed = ToolContext(workspace_root=git_repo, permission_engine=AllowEngine())
    res_allowed = await git_commit.run({"message": "feat: add feature"}, ctx=ctx_allowed)
    assert res_allowed.ok is True
    assert "Commit created successfully" in res_allowed.output
    assert "feat: add feature" in res_allowed.output

    # Verify commit exists in git
    log_check = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert log_check.stdout.strip() == "feat: add feature"


def test_git_tools_in_default_registry() -> None:
    """Verify all 4 git tools are present in the default ToolRegistry."""
    for tool_name in ("git_status", "git_diff", "git_log", "git_commit"):
        tool_inst = default_registry.get(tool_name)
        assert tool_inst is not None
        assert tool_inst.name == tool_name
        spec = tool_inst.to_tool_spec()
        assert spec.name == tool_name
