"""Tests for workspace boundaries, traversal attacks, symlink guards, and ignore parsing."""

from pathlib import Path

import pytest

from lathe.safety.workspace import (
    DEFAULT_IGNORED_DIRS,
    PathEscapeError,
    Workspace,
)


def test_workspace_normal_resolution(tmp_path: Path) -> None:
    """Workspace resolves relative paths within root correctly."""
    ws = Workspace(tmp_path)
    file_path = tmp_path / "hello.txt"
    file_path.write_text("world", encoding="utf-8")

    resolved = ws.resolve_path("hello.txt")
    assert resolved == file_path.resolve()
    assert ws.relpath(resolved) == "hello.txt"


def test_workspace_absolute_path_inside_root(tmp_path: Path) -> None:
    """Absolute paths within workspace root are safely resolved."""
    ws = Workspace(tmp_path)
    sub = tmp_path / "src"
    sub.mkdir()
    abs_path = sub / "main.py"

    resolved = ws.resolve_path(str(abs_path))
    assert resolved == abs_path.resolve()
    assert ws.relpath(resolved) == "src/main.py"


def test_workspace_path_escape_dotdot(tmp_path: Path) -> None:
    """Relative traversal with '..' outside root must raise PathEscapeError."""
    ws = Workspace(tmp_path)

    with pytest.raises(PathEscapeError) as exc_info:
        ws.resolve_path("../outside.txt")
    assert "escapes workspace root" in str(exc_info.value)

    with pytest.raises(PathEscapeError):
        ws.resolve_path("sub/../../outside.txt")


def test_workspace_path_escape_absolute(tmp_path: Path) -> None:
    """Absolute paths pointing outside root must raise PathEscapeError."""
    ws = Workspace(tmp_path)

    outside = Path("/etc/passwd")
    with pytest.raises(PathEscapeError) as exc_info:
        ws.resolve_path(str(outside))
    assert "escapes workspace root" in str(exc_info.value)


def test_workspace_symlink_pointing_outside(tmp_path: Path) -> None:
    """Symlinks pointing to targets outside workspace must be rejected."""
    outside_dir = tmp_path.parent / "outside_dir"
    outside_dir.mkdir(exist_ok=True)
    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("secret_content")

    ws = Workspace(tmp_path)
    symlink_file = tmp_path / "leak_symlink.txt"
    symlink_file.symlink_to(outside_file)

    with pytest.raises(PathEscapeError) as exc_info:
        ws.resolve_path("leak_symlink.txt")
    assert "escapes workspace root" in str(exc_info.value)

    # Symlink directory pointing outside
    symlink_dir = tmp_path / "leak_dir"
    symlink_dir.symlink_to(outside_dir)

    with pytest.raises(PathEscapeError):
        ws.resolve_path("leak_dir/secret.txt")

    with pytest.raises(PathEscapeError):
        ws.resolve_path("leak_dir/nonexistent.txt")


def test_workspace_symlink_inside_allowed(tmp_path: Path) -> None:
    """Symlinks pointing inside the workspace are valid."""
    ws = Workspace(tmp_path)
    target = tmp_path / "original.txt"
    target.write_text("legit")

    symlink_file = tmp_path / "internal_link.txt"
    symlink_file.symlink_to(target)

    resolved = ws.resolve_path("internal_link.txt")
    assert resolved == target.resolve()


def test_workspace_null_byte_rejected(tmp_path: Path) -> None:
    """Paths containing null bytes must be rejected."""
    ws = Workspace(tmp_path)
    with pytest.raises(PathEscapeError):
        ws.resolve_path("foo\0bar.txt")


def test_workspace_default_ignored_dirs(tmp_path: Path) -> None:
    """Default directories (node_modules, .venv, .git, build, dist) are ignored."""
    ws = Workspace(tmp_path)

    for ignored_dir in DEFAULT_IGNORED_DIRS:
        assert ws.is_ignored(f"{ignored_dir}/file.txt", is_dir=False) is True
        assert ws.is_ignored(ignored_dir, is_dir=True) is True

    assert ws.is_ignored("pkg.egg-info/entry.txt") is True
    assert ws.is_ignored("src/lathe/cli.py") is False


def test_workspace_gitignore_parsing(tmp_path: Path) -> None:
    """.gitignore patterns including wildcards, comments, and negation are respected."""
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(
        """
        # Comment line
        *.log
        temp/
        !special.log
        /root_only.txt
        src/**/*.tmp
        """,
        encoding="utf-8",
    )

    ws = Workspace(tmp_path)

    assert ws.is_ignored("app.log") is True
    assert ws.is_ignored("logs/server.log") is True
    # Negation
    assert ws.is_ignored("special.log") is False
    # Directory only
    assert ws.is_ignored("temp/data.json", is_dir=False) is True
    assert ws.is_ignored("temp", is_dir=True) is True
    # Anchored to root
    assert ws.is_ignored("root_only.txt") is True
    assert ws.is_ignored("nested/root_only.txt") is False
    # Globstar
    assert ws.is_ignored("src/sub/deep/test.tmp") is True
    assert ws.is_ignored("docs/guide.tmp") is False


def test_workspace_latheignore_parsing(tmp_path: Path) -> None:
    """.latheignore rules are loaded and prioritized alongside .gitignore."""
    latheignore = tmp_path / ".latheignore"
    latheignore.write_text(
        """
        secrets/
        *.secret
        """,
        encoding="utf-8",
    )

    ws = Workspace(tmp_path)
    assert ws.is_ignored("secrets/keys.json") is True
    assert ws.is_ignored("config.secret") is True
    assert ws.is_ignored("config.json") is False


def test_guard_home_and_root_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Home directory and / are rejected as project folders."""
    from lathe.safety.guard import check_is_project_folder

    is_proj_home, msg_home = check_is_project_folder(Path.home())
    assert is_proj_home is False
    assert "Not in a project folder — cd into a project for full features." in (msg_home or "")

    is_proj_root, msg_root = check_is_project_folder(Path("/"))
    assert is_proj_root is False
    assert "Not in a project folder — cd into a project for full features." in (msg_root or "")


def test_guard_git_repository(tmp_path: Path) -> None:
    """Folder containing .git is recognized as a valid project folder."""
    from lathe.safety.guard import check_is_project_folder

    (tmp_path / ".git").mkdir()
    is_proj, msg = check_is_project_folder(tmp_path)
    assert is_proj is True
    assert msg is None
