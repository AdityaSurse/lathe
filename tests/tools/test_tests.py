"""Unit and integration tests for run_tests tool and test command detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from lathe.tools.base import ToolContext
from lathe.tools.registry import default_registry
from lathe.tools.tests import (
    detect_test_command,
    parse_test_output,
)


def test_detect_test_command_from_config(tmp_path: Path) -> None:
    """Configured [project].test_command overrides workspace file detection."""
    assert detect_test_command(tmp_path, "pytest tests/unit -v") == "pytest tests/unit -v"


def test_detect_test_command_python(tmp_path: Path) -> None:
    """Detect pytest from pyproject.toml or tests/ directory."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    assert detect_test_command(tmp_path) == "pytest"

    # Alternatively test_*.py file
    tmp2 = tmp_path / "sub"
    tmp2.mkdir()
    (tmp2 / "test_sample.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    assert detect_test_command(tmp2) == "pytest"


def test_detect_test_command_node(tmp_path: Path) -> None:
    """Detect npm, pnpm, or yarn test based on lockfile presence."""
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    assert detect_test_command(tmp_path) == "npm test"

    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert detect_test_command(tmp_path) == "pnpm test"

    (tmp_path / "pnpm-lock.yaml").unlink()
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    assert detect_test_command(tmp_path) == "yarn test"


def test_detect_test_command_rust(tmp_path: Path) -> None:
    """Detect cargo test from Cargo.toml."""
    (tmp_path / "Cargo.toml").write_text("[package]\nname='test'\n", encoding="utf-8")
    assert detect_test_command(tmp_path) == "cargo test"


def test_detect_test_command_go(tmp_path: Path) -> None:
    """Detect go test ./... from go.mod."""
    (tmp_path / "go.mod").write_text("module example.com/test\n", encoding="utf-8")
    assert detect_test_command(tmp_path) == "go test ./..."


def test_detect_test_command_ctest(tmp_path: Path) -> None:
    """Detect ctest from CMakeLists.txt."""
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n", encoding="utf-8"
    )
    assert detect_test_command(tmp_path) == "ctest"


def test_detect_test_command_makefile(tmp_path: Path) -> None:
    """Detect make test from Makefile with test target."""
    (tmp_path / "Makefile").write_text(
        "all:\n\techo all\ntest:\n\techo testing\n", encoding="utf-8"
    )
    assert detect_test_command(tmp_path) == "make test"


def test_parse_pytest_passing_output() -> None:
    """Parse passing pytest output."""
    output = "===== 278 passed in 4.25s ====="
    res = parse_test_output("pytest", 0, output)
    assert res.is_success is True
    assert res.passed == 278
    assert res.failed == 0
    assert res.failing_output is None


def test_parse_pytest_failing_output() -> None:
    """Parse failing pytest output and extract first failure section."""
    output = """
============================= test session starts ==============================
collected 2 items

test_calc.py .F                                                           [100%]

=================================== FAILURES ===================================
__________________________________ test_calc ___________________________________

    def test_calc():
>       assert add(1, 2) == 4
E       assert 3 == 4

test_calc.py:5: AssertionError
=========================== short test summary info ============================
FAILED test_calc.py::test_calc - assert 3 == 4
========================= 1 failed, 1 passed in 0.05s ==========================
"""
    res = parse_test_output("pytest", 1, output)
    assert res.is_success is False
    assert res.passed == 1
    assert res.failed == 1
    assert res.failing_output is not None
    assert "test_calc" in res.failing_output
    assert "AssertionError" in res.failing_output


def test_parse_cargo_output() -> None:
    """Parse cargo test output."""
    output = """
running 5 tests
test tests::test_add ... ok
test tests::test_sub ... FAILED
test tests::test_mul ... ok

failures:

---- tests::test_sub stdout ----
thread 'tests::test_sub' panicked at 'assertion failed: `(left == right)`

failures:
    tests::test_sub

test result: FAILED. 4 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out
"""
    res = parse_test_output("cargo test", 101, output)
    assert res.is_success is False
    assert res.passed == 4
    assert res.failed == 1
    assert res.failing_output is not None
    assert "tests::test_sub" in res.failing_output


def test_parse_go_output() -> None:
    """Parse go test output."""
    output = """
=== RUN   TestAdd
--- PASS: TestAdd (0.00s)
=== RUN   TestSub
--- FAIL: TestSub (0.00s)
    calc_test.go:12: got 3, want 4
FAIL
exit status 1
FAIL	example.com/calc	0.005s
"""
    res = parse_test_output("go test ./...", 1, output)
    assert res.is_success is False
    assert res.passed == 1
    assert res.failed == 1
    assert res.failing_output is not None
    assert "TestSub" in res.failing_output


@pytest.mark.asyncio
async def test_run_tests_tool_in_registry(tmp_path: Path) -> None:
    """Verify run_tests tool executes successfully and is present in default_registry."""
    tool = default_registry.get("run_tests")
    assert tool is not None
    assert tool.name == "run_tests"
    assert tool.risk_level == "execute"

    # Setup workspace with a passing python test
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / "test_sample.py").write_text("def test_ok(): assert True\n", encoding="utf-8")

    ctx = ToolContext(workspace_root=tmp_path)
    res = await tool.run({}, ctx=ctx)
    assert res.ok is True
    assert "Status: PASSED" in res.output
    assert res.metadata.get("passed") == 1
