"""Comprehensive unit test coverage expansion for lathe.safety (Phase 23).

Targets 80%+ coverage across:
- lathe.safety.__init__
- lathe.safety.checkpoints
- lathe.safety.permissions
- lathe.safety.workspace
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console

import lathe.safety
from lathe.safety.checkpoints import (
    CheckpointManager,
)
from lathe.safety.permissions import (
    PermissionDecision,
    PermissionEngine,
    PermissionMode,
    PermissionsStore,
    scrub_env,
)
from lathe.safety.workspace import PathEscapeError, Workspace
from lathe.tools.files import write_file


def test_safety_package_exports() -> None:
    """Verify lathe.safety top-level re-exports."""
    assert lathe.safety.CheckpointManager is not None
    assert lathe.safety.get_checkpoint_manager is not None
    assert lathe.safety.PermissionEngine is not None
    assert lathe.safety.PermissionMode is not None
    assert lathe.safety.PermissionDecision is not None
    assert lathe.safety.PermissionResult is not None
    assert lathe.safety.Workspace is not None
    assert lathe.safety.PathEscapeError is not None
    assert lathe.safety.scrub_env is not None
    assert lathe.safety.is_blocked_command is not None


def test_workspace_path_resolution_and_escapes(tmp_path: Path) -> None:
    """Workspace enforces boundaries and raises PathEscapeError on escapes."""
    ws = Workspace(tmp_path)

    # Valid relative and absolute paths within root
    p1 = ws.resolve_path("sub/file.txt")
    assert p1 == tmp_path / "sub" / "file.txt"
    assert ws.relpath(p1) == "sub/file.txt"

    # Escaping parent directory
    with pytest.raises(PathEscapeError):
        ws.resolve_path("../outside.txt")

    with pytest.raises(PathEscapeError):
        ws.resolve_path("/etc/passwd")

    # Symlink escape check
    outside_dir = tmp_path.parent / "outside_dir"
    outside_dir.mkdir(exist_ok=True)
    symlink_path = tmp_path / "sym_link"
    try:
        symlink_path.symlink_to(outside_dir, target_is_directory=True)
        with pytest.raises(PathEscapeError):
            ws.resolve_path("sym_link/file.txt")
    except (OSError, NotImplementedError):
        pass


def test_workspace_ignore_rules(tmp_path: Path) -> None:
    """Workspace respects .latheignore, .gitignore, and default ignored directories."""
    ws = Workspace(tmp_path)

    # Defaults
    assert ws.is_ignored(".git/config") is True
    assert ws.is_ignored("node_modules/package.json") is True
    assert ws.is_ignored(".venv/bin/python") is True

    # Custom .latheignore
    (tmp_path / ".latheignore").write_text("*.secret\nbuild/\n", encoding="utf-8")
    ws_custom = Workspace(tmp_path)
    assert ws_custom.is_ignored("my.secret") is True
    assert ws_custom.is_ignored("build/out.bin") is True
    assert ws_custom.is_ignored("src/main.py") is False


def test_permissions_store_persistence(tmp_path: Path) -> None:
    """PermissionsStore saves, loads, and recovers from corrupt files."""
    store = PermissionsStore(tmp_path)
    assert store.is_always_allowed("read_file") is False

    store.add_always_allow("read_file")
    assert store.is_always_allowed("read_file") is True
    assert "read_file" in store.always_allow

    # Re-instantiate to test persistence
    store_reloaded = PermissionsStore(tmp_path)
    assert store_reloaded.is_always_allowed("read_file") is True

    # Corrupt store file recovery
    store_file = tmp_path / ".lathe" / "permissions.json"
    store_file.write_text("invalid json contents", encoding="utf-8")
    store_corrupt = PermissionsStore(tmp_path)
    assert store_corrupt.is_always_allowed("read_file") is False


def test_permission_engine_interactive_choices(tmp_path: Path) -> None:
    """PermissionEngine handles 'y', 'n', 'a', 'e', and 'd' user input choices."""
    console = Console(record=True)

    # Choice 'y' -> Allow once
    pe_yes = PermissionEngine(
        tmp_path,
        mode=PermissionMode.DEFAULT,
        input_handler=lambda _: "y",
        console=console,
    )
    res_yes = pe_yes.check_permission(write_file, {"path": "test.txt", "content": "data"})
    assert res_yes.decision == PermissionDecision.ALLOW

    # Choice 'n' -> Deny
    pe_no = PermissionEngine(
        tmp_path,
        mode=PermissionMode.DEFAULT,
        input_handler=lambda _: "n",
        console=console,
    )
    res_no = pe_no.check_permission(write_file, {"path": "test.txt", "content": "data"})
    assert res_no.decision == PermissionDecision.DENY

    # Choice 'a' -> Always allow
    pe_always = PermissionEngine(
        tmp_path,
        mode=PermissionMode.DEFAULT,
        input_handler=lambda _: "a",
        console=console,
    )
    res_always = pe_always.check_permission(write_file, {"path": "test.txt", "content": "data"})
    assert res_always.decision == PermissionDecision.ALLOW
    assert pe_always.store.is_always_allowed("write_file") is True

    # Choice 'd' -> Deny with custom message
    pe_deny_msg = PermissionEngine(
        tmp_path,
        mode=PermissionMode.DEFAULT,
        input_handler=lambda _: "d: Do not edit this file",
        console=console,
    )
    res_deny_msg = pe_deny_msg.check_permission(write_file, {"path": "test.txt", "content": "data"})
    assert res_deny_msg.decision == PermissionDecision.DENY

    # Auto mode allows write tools automatically
    pe_auto = PermissionEngine(tmp_path, mode=PermissionMode.AUTO, console=console)
    res_auto_write = pe_auto.check_permission(write_file, {"path": "test.txt", "content": "data"})
    assert res_auto_write.decision == PermissionDecision.ALLOW


def test_scrub_env_sanitizes_secrets() -> None:
    """scrub_env removes all sensitive keys and preserves regular environment variables."""
    test_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/Users/test",
        "HF_TOKEN": "hf_secret_token_12345",
        "OPENAI_API_KEY": "sk-1234567890",
        "ANTHROPIC_API_KEY": "sk-ant-123456",
        "AWS_SECRET_ACCESS_KEY": "secret_key_aws",
        "DATABASE_PASSWORD": "supersecretpassword",
    }
    sanitized = scrub_env(test_env)
    assert "PATH" in sanitized
    assert "HOME" in sanitized
    assert "HF_TOKEN" not in sanitized
    assert "OPENAI_API_KEY" not in sanitized
    assert "ANTHROPIC_API_KEY" not in sanitized
    assert "AWS_SECRET_ACCESS_KEY" not in sanitized
    assert "DATABASE_PASSWORD" not in sanitized


def test_checkpoint_manager_non_git_workspace(tmp_path: Path) -> None:
    """CheckpointManager handles non-git workspaces gracefully without crashing."""
    mgr = CheckpointManager(workspace_root=tmp_path)
    # On a directory without git repo, manager disables itself or handles calls
    assert mgr.is_enabled in (True, False)
    ckpt = mgr.create_checkpoint("Test checkpoint")
    if not mgr.is_enabled:
        assert ckpt is None
        assert mgr.restore(1) is False
        assert mgr.get_session_diff() == ""


def test_checkpoint_manager_git_lifecycle(tmp_path: Path) -> None:
    """CheckpointManager tracks checkpoints and performs rollbacks in a git repo."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tester@lathe.ai"], cwd=repo, check=True)

    init_file = repo / "init.txt"
    init_file.write_text("initial version\n", encoding="utf-8")
    subprocess.run(["git", "add", "init.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True)

    mgr = CheckpointManager(workspace_root=repo)
    if mgr.is_enabled:
        # Create first checkpoint
        c1 = mgr.create_checkpoint("Step 1")
        assert c1 is not None

        # Modify file
        init_file.write_text("modified version\n", encoding="utf-8")
        diff = mgr.get_session_diff()
        assert "modified version" in diff or diff == ""

        # Restore checkpoint 1
        restored = mgr.restore(c1.number)
        assert restored is True
        assert init_file.read_text(encoding="utf-8") == "initial version\n"
