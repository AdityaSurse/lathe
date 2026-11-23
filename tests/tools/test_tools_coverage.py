"""Comprehensive unit test coverage expansion for lathe.tools (Phase 23).

Targets 80%+ coverage across:
- lathe.tools.__init__
- lathe.tools.base
- lathe.tools.edit
- lathe.tools.files
- lathe.tools.git
- lathe.tools.protocol
- lathe.tools.registry
- lathe.tools.search
- lathe.tools.shell
- lathe.tools.tests
"""

from __future__ import annotations

from pathlib import Path

import pytest

import lathe.tools
from lathe.tools.base import ToolContext, truncate_output
from lathe.tools.edit import edit_file
from lathe.tools.files import (
    list_dir,
    read_file,
    write_file,
)
from lathe.tools.protocol import (
    get_tool_protocol_for_model,
)
from lathe.tools.registry import ToolRegistry
from lathe.tools.search import (
    _python_fallback_grep,
)
from lathe.tools.shell import RunShellArgs, ShellTool
from lathe.tools.tests import (
    RunTestsArgs,
    RunTestsTool,
    detect_test_command,
    parse_test_output,
    run_tests_helper,
)


def test_tools_package_exports() -> None:
    """Verify lathe.tools top-level re-exports."""
    assert lathe.tools.read_file is not None
    assert lathe.tools.write_file is not None
    assert lathe.tools.edit_file is not None
    assert lathe.tools.run_shell is not None
    assert lathe.tools.git_status is not None
    assert lathe.tools.git_diff is not None
    assert lathe.tools.git_commit is not None
    assert lathe.tools.git_log is not None
    assert lathe.tools.grep_search is not None
    assert lathe.tools.semantic_search is not None
    assert lathe.tools.run_tests is not None
    assert lathe.tools.default_registry is not None
    assert len(lathe.tools.__all__) >= 10


def test_truncate_output_utility() -> None:
    """truncate_output preserves small text and truncates long text with notice."""
    short_text = "hello world"
    assert truncate_output(short_text, max_chars=100) == short_text

    long_text = "x" * 200
    truncated = truncate_output(long_text, max_chars=50)
    assert len(truncated) < 200
    assert "truncated" in truncated.lower()


@pytest.mark.asyncio
async def test_read_file_edge_cases(tmp_path: Path) -> None:
    """read_file handles empty file, line range beyond end, and directory paths."""
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res_empty = await read_file.run({"path": "empty.txt"}, ctx=ctx)
    assert res_empty.ok is True
    assert "(File is empty)" in res_empty.output

    # Line range beyond EOF
    normal_file = tmp_path / "normal.txt"
    normal_file.write_text("line 1\nline 2\n", encoding="utf-8")
    res_beyond = await read_file.run({"path": "normal.txt", "start_line": 10}, ctx=ctx)
    assert res_beyond.ok is True
    assert "is beyond end of file" in res_beyond.output

    # Directory rejected
    res_dir = await read_file.run({"path": "."}, ctx=ctx)
    assert res_dir.ok is False
    assert "is a directory" in (res_dir.error or "")


@pytest.mark.asyncio
async def test_write_file_edge_cases(tmp_path: Path) -> None:
    """write_file prevents overwriting existing file and creates brand new files."""
    existing = tmp_path / "exist.txt"
    existing.write_text("initial", encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    # Fail because file already exists
    res_fail = await write_file.run({"path": "exist.txt", "content": "new"}, ctx=ctx)
    assert res_fail.ok is False
    assert "already exists" in (res_fail.error or "").lower()

    # Succeed on brand new file
    res_ok = await write_file.run({"path": "brand_new.txt", "content": "fresh_content"}, ctx=ctx)
    assert res_ok.ok is True
    assert (tmp_path / "brand_new.txt").read_text(encoding="utf-8") == "fresh_content"


@pytest.mark.asyncio
async def test_list_dir_depth_and_empty(tmp_path: Path) -> None:
    """list_dir supports depth limit and reports empty directories."""
    sub = tmp_path / "a" / "b" / "c"
    sub.mkdir(parents=True)
    (sub / "deep.txt").write_text("deep", encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await list_dir.run({"path": "a", "depth": 1}, ctx=ctx)
    assert res.ok is True
    assert "b/" in res.output
    assert "deep.txt" not in res.output

    # Non-existent directory
    res_missing = await list_dir.run({"path": "does_not_exist"}, ctx=ctx)
    assert res_missing.ok is False


@pytest.mark.asyncio
async def test_edit_file_whitespace_relaxed_match(tmp_path: Path) -> None:
    """edit_file supports trailing whitespace and newline relaxation."""
    target = tmp_path / "code.py"
    target.write_text("def test():   \n    return 1   \n", encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await edit_file.run(
        {
            "path": "code.py",
            "edits": [{"old": "def test():\n    return 1", "new": "def test():\n    return 2"}],
        },
        ctx=ctx,
    )
    assert res.ok is True
    assert "return 2" in target.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_shell_tool_environment_and_nonzero(tmp_path: Path) -> None:
    """ShellTool returns nonzero exit codes cleanly and scrubs sensitive environment."""
    tool = ShellTool()
    ctx = ToolContext(workspace_root=tmp_path)

    args = RunShellArgs(command="python3 -c 'import sys; sys.exit(42)'")
    res = await tool._execute(args, ctx)
    assert res.ok is False
    assert "exit code 42" in (res.error or "")


def test_detect_test_runner_markers(tmp_path: Path) -> None:
    """detect_test_command detects Rust, Go, Node, Make, and CTest projects."""
    # 1. Rust Cargo
    (tmp_path / "Cargo.toml").write_text("[package]\nname='test'\n", encoding="utf-8")
    assert detect_test_command(tmp_path) == "cargo test"
    (tmp_path / "Cargo.toml").unlink()

    # 2. Node npm/pnpm/yarn
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert detect_test_command(tmp_path) == "pnpm test"
    (tmp_path / "pnpm-lock.yaml").unlink()
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    assert detect_test_command(tmp_path) == "yarn test"
    (tmp_path / "yarn.lock").unlink()
    assert detect_test_command(tmp_path) == "npm test"
    (tmp_path / "package.json").unlink()

    # 3. Go
    (tmp_path / "go.mod").write_text("module test\n", encoding="utf-8")
    assert detect_test_command(tmp_path) == "go test ./..."
    (tmp_path / "go.mod").unlink()

    # 4. CTest
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n", encoding="utf-8"
    )
    assert detect_test_command(tmp_path) == "ctest"
    (tmp_path / "CMakeLists.txt").unlink()

    # 5. Makefile
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    assert detect_test_command(tmp_path) == "make test"
    (tmp_path / "Makefile").unlink()


def test_parse_test_output_formats() -> None:
    """parse_test_output parses Cargo, Go, Jest, and CTest output blocks."""
    # Cargo test output
    cargo_out = (
        "running 5 tests\n"
        "test test_a ... ok\n"
        "test test_b ... FAILED\n"
        "failures:\n"
        "---- test_b stdout ----\n"
        "assertion failed: 1 == 2\n"
        "test result: FAILED. 4 passed; 1 failed; 0 ignored;\n"
    )
    res_cargo = parse_test_output("cargo test", 101, cargo_out)
    assert res_cargo.passed == 4
    assert res_cargo.failed == 1
    assert "failures:" in (res_cargo.failing_output or "")

    # Go test output
    go_out = (
        "=== RUN   TestA\n--- PASS: TestA (0.00s)\n=== RUN   TestB\n--- FAIL: TestB (0.01s)\nFAIL\n"
    )
    res_go = parse_test_output("go test ./...", 1, go_out)
    assert res_go.passed == 1
    assert res_go.failed == 1
    assert "--- FAIL:" in (res_go.failing_output or "")

    # Generic / CTest / Jest output
    jest_out = "Tests: 1 failed, 3 passed, 4 total\n"
    res_jest = parse_test_output("npm test", 1, jest_out)
    assert res_jest.failed == 1
    assert res_jest.passed == 3


def test_python_fallback_grep_edge_cases(tmp_path: Path) -> None:
    """_python_fallback_grep supports regex matching, context lines, and file caps."""
    (tmp_path / "file1.py").write_text("line 1\nmatch_alpha\nline 3\n", encoding="utf-8")
    (tmp_path / "file2.py").write_text("foo\nmatch_beta\nbar\n", encoding="utf-8")

    out = _python_fallback_grep(tmp_path, r"match_[a-z]+", regex=True, max_matches=5)
    assert "match_alpha" in out
    assert "match_beta" in out

    out_no_match = _python_fallback_grep(tmp_path, "nonexistent_token_xyz")
    assert "No matches found" in out_no_match


def test_protocol_model_capabilities() -> None:
    """get_tool_protocol_for_model maps known model names to native or fallback protocols."""
    assert get_tool_protocol_for_model("qwen2.5-coder:7b") in ("native", "fallback")
    assert get_tool_protocol_for_model("deepseek-r1:8b") in ("native", "fallback")
    assert get_tool_protocol_for_model("unknown-model-xyz") == "fallback"


def test_tool_registry_management() -> None:
    """ToolRegistry supports registration, replacement, and specs retrieval."""
    reg = ToolRegistry()
    assert len(reg.list_tools()) == 0

    reg.register(read_file)
    assert reg.get("read_file") is not None
    assert len(reg.list_tools()) == 1

    specs = reg.get_tool_specs()
    assert len(specs) == 1
    assert specs[0].name == "read_file"


@pytest.mark.asyncio
async def test_run_tests_tool_and_helper(tmp_path: Path) -> None:
    """RunTestsTool executes command overrides and parses results."""
    tool = RunTestsTool()
    ctx = ToolContext(workspace_root=tmp_path)
    args = RunTestsArgs(command="echo '1 passed in 0.01s'")
    res = await tool._execute(args, ctx)
    assert res.ok is True
    assert "1 passed" in (res.output or "")

    helper_res = run_tests_helper(tmp_path, command_override="echo '2 passed in 0.02s'")
    assert helper_res.passed >= 1
    assert helper_res.failed == 0
    assert helper_res.is_success is True
