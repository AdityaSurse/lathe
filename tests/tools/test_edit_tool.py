"""Tests for the atomic search-and-replace edit_file tool (Phase 10)."""

from pathlib import Path

import pytest

from lathe.tools.base import ToolContext
from lathe.tools.edit import (
    calculate_diff,
    detect_encoding_and_newline,
    edit_file,
)
from lathe.tools.registry import default_registry
from lathe.ui.diff import create_diff_panel, print_diff_panel

# =====================================================================
# 1. Exact Match Tests
# =====================================================================


@pytest.mark.asyncio
async def test_edit_file_exact_match(tmp_path: Path) -> None:
    """edit_file replaces an exact single match and returns the diff summary."""
    test_file = tmp_path / "hello.py"
    initial_content = "def greet():\n    return 'hello world'\n"
    test_file.write_text(initial_content, encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await edit_file.run(
        {
            "path": "hello.py",
            "edits": [
                {
                    "old": "    return 'hello world'",
                    "new": "    # Added comment\n    return 'hello lathe'",
                }
            ],
        },
        ctx=ctx,
    )

    assert res.ok is True
    assert "Successfully edited 'hello.py'" in res.output
    assert "+2 -1 lines" in res.output
    assert res.metadata["summary"] == "+2 -1 lines"
    assert res.metadata["added"] == 2
    assert res.metadata["removed"] == 1

    expected_content = "def greet():\n    # Added comment\n    return 'hello lathe'\n"
    assert test_file.read_text(encoding="utf-8") == expected_content


# =====================================================================
# 2. Fuzzy Whitespace Matching Tests
# =====================================================================


@pytest.mark.asyncio
async def test_edit_file_fuzzy_whitespace_indentation(tmp_path: Path) -> None:
    """edit_file succeeds when old block has different indentation than the file."""
    test_file = tmp_path / "indent.py"
    # 4 spaces indentation in file
    initial_content = "class Worker:\n    def run(self):\n        x = 10\n        return x\n"
    test_file.write_text(initial_content, encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    # Model sends 2 spaces indentation in 'old'
    res = await edit_file.run(
        {
            "path": "indent.py",
            "edits": [
                {
                    "old": "  def run(self):\n    x = 10\n    return x\n",
                    "new": "    def run(self):\n        return 42\n",
                }
            ],
        },
        ctx=ctx,
    )

    assert res.ok is True
    assert "Successfully edited 'indent.py'" in res.output
    assert "+1 -2 lines" in res.output

    expected = "class Worker:\n    def run(self):\n        return 42\n"
    assert test_file.read_text(encoding="utf-8") == expected


@pytest.mark.asyncio
async def test_edit_file_fuzzy_whitespace_inline_tokens(tmp_path: Path) -> None:
    """edit_file succeeds on inline token-level whitespace differences."""
    test_file = tmp_path / "inline.py"
    test_file.write_text("result = compute( a , b , c )\n", encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await edit_file.run(
        {
            "path": "inline.py",
            "edits": [
                {
                    "old": "compute(a, b, c)",
                    "new": "calculate(a, b, c)",
                }
            ],
        },
        ctx=ctx,
    )

    assert res.ok is True
    assert test_file.read_text(encoding="utf-8") == "result = calculate(a, b, c)\n"


# =====================================================================
# 3. Ambiguous Match Error Tests
# =====================================================================


@pytest.mark.asyncio
async def test_edit_file_ambiguous_match_error(tmp_path: Path) -> None:
    """edit_file refuses edits matching multiple locations and reports line numbers."""
    test_file = tmp_path / "ambiguous.py"
    initial_content = "def foo():\n    return 1\n\ndef bar():\n    return 1\n"
    test_file.write_text(initial_content, encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await edit_file.run(
        {
            "path": "ambiguous.py",
            "edits": [
                {
                    "old": "    return 1\n",
                    "new": "    return 2\n",
                }
            ],
        },
        ctx=ctx,
    )

    assert res.ok is False
    assert "Ambiguous edit" in (res.error or "")
    assert "found 2 exact matches" in (res.error or "")
    assert "[2, 5]" in (res.error or "")

    # Crucial: file on disk must NOT be modified
    assert test_file.read_text(encoding="utf-8") == initial_content


@pytest.mark.asyncio
async def test_edit_file_ambiguous_fuzzy_match_error(tmp_path: Path) -> None:
    """Fuzzy whitespace match matching more than 1 location is rejected."""
    test_file = tmp_path / "fuzzy_ambiguous.py"
    initial_content = "  item = 100\n      item = 100\n"
    test_file.write_text(initial_content, encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await edit_file.run(
        {
            "path": "fuzzy_ambiguous.py",
            "edits": [
                {
                    "old": "item = 100",
                    "new": "item = 200",
                }
            ],
        },
        ctx=ctx,
    )

    assert res.ok is False
    assert "Ambiguous edit" in (res.error or "")
    assert test_file.read_text(encoding="utf-8") == initial_content


# =====================================================================
# 4. Multi-Edit Atomic Rollback Tests
# =====================================================================


@pytest.mark.asyncio
async def test_edit_file_multi_edit_atomic_rollback(tmp_path: Path) -> None:
    """If one edit in a batch fails, NO edits are applied to the disk (all or nothing)."""
    test_file = tmp_path / "atomic.py"
    initial_content = "def step_one():\n    pass\n\ndef step_two():\n    pass\n"
    test_file.write_text(initial_content, encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    # Edit 1 is valid, but Edit 2 is nonexistent
    res = await edit_file.run(
        {
            "path": "atomic.py",
            "edits": [
                {
                    "old": "def step_one():\n    pass",
                    "new": "def step_one():\n    return 1",
                },
                {
                    "old": "def step_nonexistent():\n    missing()",
                    "new": "def step_two():\n    return 2",
                },
            ],
        },
        ctx=ctx,
    )

    assert res.ok is False
    assert "Edit 2 of 2 failed" in (res.error or "")
    assert "Failed to find match for 'old' block" in (res.error or "")

    # Atomic guarantee: step_one was NOT changed on disk
    assert test_file.read_text(encoding="utf-8") == initial_content


@pytest.mark.asyncio
async def test_edit_file_multi_edit_sequential_success(tmp_path: Path) -> None:
    """Multiple valid edits apply sequentially in one atomic transaction."""
    test_file = tmp_path / "batch.py"
    initial_content = "x = 1\ny = 2\nz = 3\n"
    test_file.write_text(initial_content, encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await edit_file.run(
        {
            "path": "batch.py",
            "edits": [
                {"old": "x = 1", "new": "x = 10"},
                {"old": "z = 3", "new": "z = 30"},
            ],
        },
        ctx=ctx,
    )

    assert res.ok is True
    assert "+2 -2 lines" in res.output
    expected = "x = 10\ny = 2\nz = 30\n"
    assert test_file.read_text(encoding="utf-8") == expected


# =====================================================================
# 5. CRLF & Encoding Preservation Tests
# =====================================================================


@pytest.mark.asyncio
async def test_edit_file_preserves_crlf(tmp_path: Path) -> None:
    """Files with Windows CRLF (\\r\\n) endings must maintain CRLF after edits."""
    test_file = tmp_path / "crlf_file.py"
    crlf_bytes = b"line 1\r\nline 2\r\nline 3\r\n"
    test_file.write_bytes(crlf_bytes)

    encoding, newline = detect_encoding_and_newline(crlf_bytes)
    assert newline == "\r\n"

    ctx = ToolContext(workspace_root=tmp_path)
    # The model may send standard \n newlines
    res = await edit_file.run(
        {
            "path": "crlf_file.py",
            "edits": [
                {
                    "old": "line 2\n",
                    "new": "line 2 modified\nline 2.5 added\n",
                }
            ],
        },
        ctx=ctx,
    )

    assert res.ok is True
    assert res.metadata["line_ending"] == "CRLF"

    written_bytes = test_file.read_bytes()
    assert b"\r\n" in written_bytes
    # Must NOT contain lone LF without CR
    assert b"\n" not in written_bytes.replace(b"\r\n", b"")
    assert written_bytes == b"line 1\r\nline 2 modified\r\nline 2.5 added\r\nline 3\r\n"


@pytest.mark.asyncio
async def test_edit_file_preserves_utf8_bom(tmp_path: Path) -> None:
    """Files with UTF-8 BOM are decoded and re-written preserving the BOM signature."""
    test_file = tmp_path / "bom_file.txt"
    bom_bytes = b"\xef\xbb\xbfTitle: Lathe\nVersion: 1\n"
    test_file.write_bytes(bom_bytes)

    ctx = ToolContext(workspace_root=tmp_path)
    res = await edit_file.run(
        {
            "path": "bom_file.txt",
            "edits": [
                {
                    "old": "Version: 1\n",
                    "new": "Version: 2\n",
                }
            ],
        },
        ctx=ctx,
    )

    assert res.ok is True
    assert res.metadata["encoding"] == "utf-8-sig"

    written_bytes = test_file.read_bytes()
    assert written_bytes.startswith(b"\xef\xbb\xbf")
    assert b"Version: 2" in written_bytes


# =====================================================================
# 6. Error Reporting & Closest Lines Recovery Tests
# =====================================================================


@pytest.mark.asyncio
async def test_edit_file_shows_closest_matching_lines(tmp_path: Path) -> None:
    """Zero matches returns an error displaying closest lines for LLM retry."""
    test_file = tmp_path / "target.py"
    content = (
        "def calculate_total(items):\n"
        "    subtotal = 0\n"
        "    for item in items:\n"
        "        subtotal += item.price\n"
        "    return subtotal\n"
    )
    test_file.write_text(content, encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await edit_file.run(
        {
            "path": "target.py",
            "edits": [
                {
                    # Slightly wrong text (tax instead of price)
                    "old": "    for item in items:\n        subtotal += item.tax",
                    "new": "    return 0",
                }
            ],
        },
        ctx=ctx,
    )

    assert res.ok is False
    assert "No exact or whitespace-insensitive match found" in (res.error or "")
    assert "Closest matching lines in the file (around line" in (res.error or "")
    assert "subtotal += item.price" in (res.error or "")


@pytest.mark.asyncio
async def test_edit_file_path_escape_rejected(tmp_path: Path) -> None:
    """edit_file rejects traversal outside workspace."""
    ctx = ToolContext(workspace_root=tmp_path)
    res = await edit_file.run(
        {
            "path": "../escape.txt",
            "edits": [{"old": "a", "new": "b"}],
        },
        ctx=ctx,
    )

    assert res.ok is False
    assert "escapes workspace root" in (res.error or "")


@pytest.mark.asyncio
async def test_edit_file_nonexistent_and_binary(tmp_path: Path) -> None:
    """edit_file handles missing and binary files gracefully."""
    ctx = ToolContext(workspace_root=tmp_path)

    # Missing file
    missing_res = await edit_file.run(
        {"path": "missing.py", "edits": [{"old": "a", "new": "b"}]},
        ctx=ctx,
    )
    assert missing_res.ok is False
    assert "File not found" in (missing_res.error or "")

    # Binary file
    bin_file = tmp_path / "data.bin"
    bin_file.write_bytes(b"\x00\x01\x02\x03\xff")
    bin_res = await edit_file.run(
        {"path": "data.bin", "edits": [{"old": "a", "new": "b"}]},
        ctx=ctx,
    )
    assert bin_res.ok is False
    assert "Cannot edit binary file" in (bin_res.error or "")


# =====================================================================
# 7. Rich UI Diff Rendering & Tool Registration Tests
# =====================================================================


def test_diff_panel_creation() -> None:
    """Rich diff panel renders unified diff with syntax styling."""
    orig = "def foo():\n    return 1\n"
    mod = "def foo():\n    return 2\n"
    diff_text, added, removed, summary = calculate_diff(orig, mod, "sample.py")

    assert summary == "+1 -1 lines"
    assert added == 1
    assert removed == 1

    panel = create_diff_panel(diff_text, "sample.py")
    assert panel.title is not None
    assert "Diff: sample.py" in str(panel.title)

    # print_diff_panel should execute without exceptions
    rendered = print_diff_panel(diff_text, "sample.py")
    assert rendered is not None


def test_edit_file_in_default_registry() -> None:
    """edit_file tool must be pre-registered in the default registry with 'write' risk."""
    tool_inst = default_registry.get("edit_file")
    assert tool_inst is not None
    assert tool_inst.risk_level == "write"
    assert "WHEN TO USE" in tool_inst.description
    assert "WHEN NOT TO USE" in tool_inst.description

    spec = tool_inst.to_tool_spec()
    assert spec.name == "edit_file"
    assert "edits" in spec.parameters["properties"]
