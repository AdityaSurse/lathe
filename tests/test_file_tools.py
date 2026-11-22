"""Tests for workspace security, ignore parsing, and file tools (Phase 9)."""

from pathlib import Path

import pytest

from lathe.safety.workspace import (
    DEFAULT_IGNORED_DIRS,
    PathEscapeError,
    Workspace,
)
from lathe.tools.base import ToolContext
from lathe.tools.files import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    glob,
    is_binary_file,
    list_dir,
    read_file,
    write_file,
)
from lathe.tools.registry import default_registry

# =====================================================================
# Workspace & Path Escape Security Tests
# =====================================================================


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


# =====================================================================
# Ignore Rules (.gitignore & .latheignore) Tests
# =====================================================================


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
    # Glob **
    assert ws.is_ignored("src/cache/scratch.tmp") is True
    assert ws.is_ignored("docs/scratch.tmp") is False


def test_workspace_latheignore_parsing(tmp_path: Path) -> None:
    """.latheignore rules supplement or override ignore patterns."""
    latheignore = tmp_path / ".latheignore"
    latheignore.write_text(
        """
        secrets.env
        private_*
        """,
        encoding="utf-8",
    )

    ws = Workspace(tmp_path)
    assert ws.is_ignored("secrets.env") is True
    assert ws.is_ignored("config/secrets.env") is True
    assert ws.is_ignored("private_keys.pem") is True
    assert ws.is_ignored("public.pem") is False


# =====================================================================
# read_file Tool Tests
# =====================================================================


@pytest.mark.asyncio
async def test_read_file_numbered_lines(tmp_path: Path) -> None:
    """read_file returns 1-based numbered lines with proper alignment."""
    test_file = tmp_path / "sample.py"
    test_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await read_file.run({"path": "sample.py"}, ctx=ctx)

    assert res.ok is True
    assert "1 | def hello():" in res.output
    assert "2 |     return 'world'" in res.output
    assert res.metadata["total_lines"] == 2
    assert res.metadata["lines_read"] == 2


@pytest.mark.asyncio
async def test_read_file_line_ranges(tmp_path: Path) -> None:
    """read_file respects start_line and end_line bounds."""
    test_file = tmp_path / "numbers.txt"
    lines = [f"line {i}" for i in range(1, 11)]
    test_file.write_text("\n".join(lines), encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await read_file.run({"path": "numbers.txt", "start_line": 3, "end_line": 5}, ctx=ctx)

    assert res.ok is True
    assert "3 | line 3" in res.output
    assert "4 | line 4" in res.output
    assert "5 | line 5" in res.output
    assert "1 | line 1" not in res.output
    assert "6 | line 6" not in res.output
    assert res.metadata["lines_read"] == 3


@pytest.mark.asyncio
async def test_read_file_invalid_line_range(tmp_path: Path) -> None:
    """start_line > end_line returns a clean error."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("content\n", encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await read_file.run({"path": "test.txt", "start_line": 5, "end_line": 2}, ctx=ctx)

    assert res.ok is False
    assert "cannot be greater than end_line" in (res.error or "")


@pytest.mark.asyncio
async def test_read_file_not_found(tmp_path: Path) -> None:
    """Non-existent file returns a friendly error message."""
    ctx = ToolContext(workspace_root=tmp_path)
    res = await read_file.run({"path": "missing.txt"}, ctx=ctx)

    assert res.ok is False
    assert "File not found" in (res.error or "")


@pytest.mark.asyncio
async def test_read_file_directory_rejected(tmp_path: Path) -> None:
    """Attempting to read a directory indicates list_dir should be used."""
    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()

    ctx = ToolContext(workspace_root=tmp_path)
    res = await read_file.run({"path": "sub"}, ctx=ctx)

    assert res.ok is False
    assert "is a directory, not a file" in (res.error or "")
    assert "list_dir" in (res.error or "")


@pytest.mark.asyncio
async def test_read_file_binary_detection(tmp_path: Path) -> None:
    """Binary files containing null bytes are detected and refused."""
    bin_file = tmp_path / "image.png"
    bin_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    assert is_binary_file(bin_file) is True

    ctx = ToolContext(workspace_root=tmp_path)
    res = await read_file.run({"path": "image.png"}, ctx=ctx)

    assert res.ok is False
    assert "file is binary" in (res.error or "")


@pytest.mark.asyncio
async def test_read_file_size_limit_rejection_and_range_allowance(tmp_path: Path) -> None:
    """Files over size limit are rejected without ranges, but allowed with ranges."""
    large_file = tmp_path / "large.txt"
    # Create file slightly larger than limit
    line = "A" * 1024 + "\n"
    target_lines = (DEFAULT_MAX_FILE_SIZE_BYTES // 1024) + 10
    large_file.write_text(line * target_lines, encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)

    # 1. Whole file read without range -> rejected with hint
    full_res = await read_file.run({"path": "large.txt"}, ctx=ctx)
    assert full_res.ok is False
    assert "exceeds" in (full_res.error or "")
    assert "size limit" in (full_res.error or "")
    assert "Please specify 'start_line' and 'end_line'" in (full_res.error or "")

    # 2. Reading specific range -> succeeds
    range_res = await read_file.run(
        {"path": "large.txt", "start_line": 1, "end_line": 3},
        ctx=ctx,
    )
    assert range_res.ok is True
    assert range_res.metadata["lines_read"] == 3


@pytest.mark.asyncio
async def test_read_file_path_escape(tmp_path: Path) -> None:
    """read_file rejects traversal outside workspace."""
    ctx = ToolContext(workspace_root=tmp_path)
    res = await read_file.run({"path": "../outside.txt"}, ctx=ctx)

    assert res.ok is False
    assert "escapes workspace root" in (res.error or "")


# =====================================================================
# list_dir Tool Tests
# =====================================================================


@pytest.mark.asyncio
async def test_list_dir_compact_tree(tmp_path: Path) -> None:
    """list_dir generates compact ASCII tree structure."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print(1)")
    (src / "util.py").write_text("print(2)")
    (tmp_path / "README.md").write_text("# Readme")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await list_dir.run({"path": ".", "depth": 2}, ctx=ctx)

    assert res.ok is True
    assert "." in res.output
    assert "src/" in res.output
    assert "app.py" in res.output
    assert "README.md" in res.output
    assert "├── " in res.output or "└── " in res.output


@pytest.mark.asyncio
async def test_list_dir_depth_limiting(tmp_path: Path) -> None:
    """list_dir depth=1 does not recurse into nested directories."""
    level1 = tmp_path / "level1"
    level1.mkdir()
    level2 = level1 / "level2"
    level2.mkdir()
    (level2 / "deep.txt").write_text("deep")

    ctx = ToolContext(workspace_root=tmp_path)

    # Depth 1 shows level1/ but not level2
    res_d1 = await list_dir.run({"path": ".", "depth": 1}, ctx=ctx)
    assert res_d1.ok is True
    assert "level1/" in res_d1.output
    assert "level2" not in res_d1.output

    # Depth 2 shows level1/ and level2/
    res_d2 = await list_dir.run({"path": ".", "depth": 2}, ctx=ctx)
    assert res_d2.ok is True
    assert "level2/" in res_d2.output
    assert "deep.txt" not in res_d2.output


@pytest.mark.asyncio
async def test_list_dir_filters_ignored_directories(tmp_path: Path) -> None:
    """list_dir omits node_modules, .venv, .git, and .gitignore entries."""
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg").mkdir()
    (tmp_path / "normal_dir").mkdir()
    (tmp_path / "normal_dir" / "main.py").write_text("")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await list_dir.run({"path": "."}, ctx=ctx)

    assert res.ok is True
    assert ".venv" not in res.output
    assert "node_modules" not in res.output
    assert "normal_dir/" in res.output


@pytest.mark.asyncio
async def test_list_dir_not_a_directory(tmp_path: Path) -> None:
    """list_dir on a file path returns an error directing to read_file."""
    file_path = tmp_path / "plain.txt"
    file_path.write_text("hello")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await list_dir.run({"path": "plain.txt"}, ctx=ctx)

    assert res.ok is False
    assert "is a file, not a directory" in (res.error or "")
    assert "read_file" in (res.error or "")


# =====================================================================
# glob Tool Tests
# =====================================================================


@pytest.mark.asyncio
async def test_glob_pattern_matching(tmp_path: Path) -> None:
    """glob finds nested matching files in alphabetical order."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "b.py").write_text("")
    (src / "a.py").write_text("")
    (tmp_path / "test.md").write_text("")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await glob.run({"pattern": "src/**/*.py"}, ctx=ctx)

    assert res.ok is True
    assert res.metadata["count"] == 2
    # Ensure alphabetical sorting
    assert res.metadata["matches"] == ["src/a.py", "src/b.py"]
    assert "src/a.py\nsrc/b.py" in res.output


@pytest.mark.asyncio
async def test_glob_filters_ignored_files(tmp_path: Path) -> None:
    """glob ignores files inside ignored directories."""
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "site.py").write_text("")

    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await glob.run({"pattern": "**/*.py"}, ctx=ctx)

    assert res.ok is True
    assert "src/app.py" in res.output
    assert ".venv" not in res.output


@pytest.mark.asyncio
async def test_glob_path_escape_rejected(tmp_path: Path) -> None:
    """glob rejects traversal patterns with '..'."""
    ctx = ToolContext(workspace_root=tmp_path)
    res = await glob.run({"pattern": "../**/*.py"}, ctx=ctx)

    assert res.ok is False
    assert "cannot contain directory traversal sequences" in (res.error or "")


@pytest.mark.asyncio
async def test_glob_no_matches(tmp_path: Path) -> None:
    """glob returns friendly message when no files match."""
    ctx = ToolContext(workspace_root=tmp_path)
    res = await glob.run({"pattern": "*.nonexistent"}, ctx=ctx)

    assert res.ok is True
    assert "No files matched pattern" in res.output
    assert res.metadata["count"] == 0


# =====================================================================
# write_file Tool Tests
# =====================================================================


@pytest.mark.asyncio
async def test_write_file_creates_new_file(tmp_path: Path) -> None:
    """write_file successfully creates a new file with parent directories."""
    ctx = ToolContext(workspace_root=tmp_path)
    content = "line 1\nline 2\nline 3"

    res = await write_file.run({"path": "nested/dir/new.txt", "content": content}, ctx=ctx)

    assert res.ok is True
    assert "Successfully created file 'nested/dir/new.txt'" in res.output
    assert res.metadata["lines"] == 3
    assert res.metadata["bytes"] == len(content.encode("utf-8"))

    created = tmp_path / "nested/dir/new.txt"
    assert created.is_file()
    assert created.read_text(encoding="utf-8") == content


@pytest.mark.asyncio
async def test_write_file_fails_if_file_already_exists(tmp_path: Path) -> None:
    """write_file strictly refuses to overwrite existing files."""
    existing = tmp_path / "existing.txt"
    existing.write_text("original content")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await write_file.run({"path": "existing.txt", "content": "overwrite attempt"}, ctx=ctx)

    assert res.ok is False
    assert "File already exists" in (res.error or "")
    assert "write_file only creates new files" in (res.error or "")
    assert "Use edit tools" in (res.error or "")

    # Content must remain unchanged
    assert existing.read_text() == "original content"


@pytest.mark.asyncio
async def test_write_file_risk_level() -> None:
    """write_file must be classified as risk_level 'write'."""
    assert write_file.risk_level == "write"
    assert read_file.risk_level == "read"
    assert list_dir.risk_level == "read"
    assert glob.risk_level == "read"


@pytest.mark.asyncio
async def test_write_file_path_escape_rejected(tmp_path: Path) -> None:
    """write_file refuses creation outside workspace."""
    ctx = ToolContext(workspace_root=tmp_path)
    res = await write_file.run({"path": "../pwned.txt", "content": "bad"}, ctx=ctx)

    assert res.ok is False
    assert "escapes workspace root" in (res.error or "")


# =====================================================================
# LLM Descriptions & Registry Registration
# =====================================================================


def test_tool_descriptions_and_specs() -> None:
    """All tools must define LLM descriptions with WHEN TO USE and WHEN NOT TO USE."""
    tools = [read_file, list_dir, glob, write_file]

    for t in tools:
        assert "WHEN TO USE" in t.description
        assert "WHEN NOT TO USE" in t.description
        spec = t.to_tool_spec()
        assert spec.name == t.name
        assert "properties" in spec.parameters


def test_file_tools_in_default_registry() -> None:
    """Phase 9 tools must be pre-registered in default_registry."""
    assert default_registry.get("read_file") is not None
    assert default_registry.get("list_dir") is not None
    assert default_registry.get("glob") is not None
    assert default_registry.get("write_file") is not None
    assert default_registry.get("echo") is not None
