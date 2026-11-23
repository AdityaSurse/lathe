"""Unit tests for Python, C, and Tool evaluation mechanisms."""

import shutil

import pytest

from lathe.bench.evaluator import (
    evaluate_c_task,
    evaluate_python_task,
    evaluate_tool_task,
    extract_code_block,
)


def test_extract_code_block():
    """Extract code from fenced markdown."""
    fenced = "```python\ndef greet():\n    return 'hello'\n```"
    assert extract_code_block(fenced, "python") == "def greet():\n    return 'hello'"

    generic = "```\nint main() { return 0; }\n```"
    assert extract_code_block(generic, "c") == "int main() { return 0; }"

    raw = "def add(a, b): return a + b"
    assert extract_code_block(raw, "python") == raw


def test_evaluate_python_task_success():
    """Valid Python solution passes assertions."""
    code = "def add(a, b): return a + b"
    test_code = "assert add(2, 3) == 5\nassert add(-1, 1) == 0"
    passed, err = evaluate_python_task(code, test_code)
    assert passed is True
    assert err is None


def test_evaluate_python_task_failure():
    """Invalid Python solution fails assertions."""
    code = "def add(a, b): return a - b"
    test_code = "assert add(2, 3) == 5"
    passed, err = evaluate_python_task(code, test_code)
    assert passed is False
    assert err is not None


def test_evaluate_python_task_syntax_error():
    """Syntax error is captured gracefully."""
    code = "def broken(:"
    test_code = "assert True"
    passed, err = evaluate_python_task(code, test_code)
    assert passed is False
    assert "SyntaxError" in str(err)


def test_evaluate_c_task():
    """Test C task compilation and execution if compiler is present and functional."""
    compiler = shutil.which("clang") or shutil.which("gcc")
    if not compiler:
        return

    code = "int multiply(int a, int b) { return a * b; }"
    test_code = """
#include <assert.h>
int multiply(int a, int b);
int main() {
    assert(multiply(3, 4) == 12);
    return 0;
}
"""
    passed, err = evaluate_c_task(code, test_code)
    if not passed and err and ("tapi error" in err or "linker command failed" in err):
        pytest.skip(f"System C compiler SDK link error: {err}")
    assert passed is True
    assert err is None


def test_evaluate_tool_task_success():
    """Valid tool call JSON matching expected tool and arguments."""
    output = (
        '<tool_call>{"name": "get_weather", "arguments": {"city": "Tokyo", "units": "celsius"}}'
        "</tool_call>"
    )
    passed, err = evaluate_tool_task(
        raw_output=output,
        expected_tool="get_weather",
        expected_args={"city": "Tokyo", "units": "celsius"},
    )
    assert passed is True
    assert err is None


def test_evaluate_tool_task_mismatched_arg():
    """Tool call with mismatched argument fails."""
    output = (
        '<tool_call>{"name": "get_weather", "arguments": {"city": "London", "units": "celsius"}}'
        "</tool_call>"
    )
    passed, err = evaluate_tool_task(
        raw_output=output,
        expected_tool="get_weather",
        expected_args={"city": "Tokyo", "units": "celsius"},
    )
    assert passed is False
    assert "mismatch" in str(err)


def test_evaluate_tool_task_invalid_json():
    """Malformed tool call text fails gracefully."""
    output = "<tool_call>not json { broken</tool_call>"
    passed, err = evaluate_tool_task(
        raw_output=output,
        expected_tool="get_weather",
        expected_args={"city": "Tokyo"},
    )
    assert passed is False
    assert err is not None
    assert "JSON" in err or "tool call" in err
