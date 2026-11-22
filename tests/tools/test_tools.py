"""Comprehensive tests for lathe.tools: schemas, execution, truncation, registry, and protocols."""

from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from lathe.llm.types import Message, ToolCall
from lathe.models.capabilities import save_capability
from lathe.tools.base import (
    EchoArgs,
    EchoTool,
    Tool,
    ToolContext,
    ToolResult,
    truncate_output,
)
from lathe.tools.protocol import (
    build_fallback_system_prompt,
    get_tool_protocol_for_model,
    parse_fallback_tool_calls,
    parse_native_tool_calls,
)
from lathe.tools.registry import ToolRegistry, default_registry, tool

# --- Schema Generation Tests ---


class CustomArgs(BaseModel):
    path: str = Field(description="File path to inspect.")
    lines: int = Field(default=10, description="Number of lines to read.")
    recursive: bool = Field(default=False, description="Whether to recurse.")


class CustomTool(Tool):
    name = "custom_reader"
    description = "Reads a file with specified options."
    args_schema = CustomArgs
    risk_level = "read"

    async def _execute(self, args: CustomArgs, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, output=f"read {args.path} lines={args.lines}")


def test_schema_generation() -> None:
    """Tool.to_tool_spec must generate a clean JSON Schema from Pydantic model."""
    custom_tool = CustomTool()
    spec = custom_tool.to_tool_spec()

    assert spec.name == "custom_reader"
    assert spec.description == "Reads a file with specified options."
    params = spec.parameters
    assert params["type"] == "object"
    assert "path" in params["properties"]
    assert "lines" in params["properties"]
    assert "recursive" in params["properties"]
    assert "path" in params["required"]
    assert "lines" not in params["required"]


def test_echo_tool_schema() -> None:
    """EchoTool must have valid schema with 'message' parameter."""
    echo = EchoTool()
    spec = echo.to_tool_spec()
    assert spec.name == "echo"
    assert "message" in spec.parameters["properties"]
    assert spec.parameters["required"] == ["message"]


# --- Execution and Validation Tests ---


@pytest.mark.asyncio
async def test_tool_successful_execution() -> None:
    """Tool must validate dictionary arguments and execute successfully."""
    echo = EchoTool()
    result = await echo.run({"message": "Hello Lathe!"})
    assert result.ok is True
    assert result.output == "Hello Lathe!"
    assert result.error is None


@pytest.mark.asyncio
async def test_tool_validation_error_structured() -> None:
    """Bad arguments must return structured error describing the missing field without crashing."""
    custom_tool = CustomTool()
    # Missing required 'path' field
    result = await custom_tool.run({"lines": 5})

    assert result.ok is False
    assert result.output == ""
    assert result.error is not None
    assert "field 'path'" in result.error
    assert "required" in result.error

    # Wrong type for 'lines' (e.g. non-numeric string)
    type_err_result = await custom_tool.run({"path": "foo.txt", "lines": "not-an-int"})
    assert type_err_result.ok is False
    assert "field 'lines'" in type_err_result.error


@pytest.mark.asyncio
async def test_tool_exception_handling() -> None:
    """Unhandled exceptions during execution must return a failed ToolResult."""

    class CrashingTool(Tool):
        name = "crash"
        description = "Throws an exception"
        args_schema = EchoArgs

        async def _execute(self, args: EchoArgs, ctx: ToolContext) -> ToolResult:
            raise RuntimeError("Disk is on fire")

    crasher = CrashingTool()
    res = await crasher.run({"message": "test"})
    assert res.ok is False
    assert "Disk is on fire" in str(res.error)


# --- Output Truncation Tests ---


def test_truncate_output_within_limit() -> None:
    """Output within max_chars must remain unchanged."""
    text = "Short text under the limit."
    assert truncate_output(text, max_chars=100) == text


def test_truncate_output_with_newlines() -> None:
    """Output exceeding limit must be truncated and report remaining line count."""
    long_text = "\n".join([f"Line {i}: some verbose content" for i in range(100)])
    truncated = truncate_output(long_text, max_chars=200)

    assert len(truncated) > 200
    assert "[truncated," in truncated
    assert "more lines]" in truncated


def test_truncate_output_without_newlines() -> None:
    """Single-line output exceeding limit must report remaining characters."""
    long_line = "A" * 500
    truncated = truncate_output(long_line, max_chars=100)

    assert "[truncated, 400 more characters]" in truncated


@pytest.mark.asyncio
async def test_tool_execution_respects_max_output_length() -> None:
    """Tool.run must automatically truncate output based on ToolContext limit."""

    class VerboseTool(Tool):
        name = "verbose"
        description = "Generates long output"
        args_schema = EchoArgs

        async def _execute(self, args: EchoArgs, ctx: ToolContext) -> ToolResult:
            lines = "\n".join([f"item {i}" for i in range(200)])
            return ToolResult(ok=True, output=lines)

    tool_instance = VerboseTool()
    ctx = ToolContext(max_output_length=150)
    res = await tool_instance.run({"message": "go"}, ctx=ctx)

    assert res.ok is True
    assert "[truncated," in res.output


# --- Registry and Decorator Tests ---


@pytest.mark.asyncio
async def test_tool_registry_and_decorator() -> None:
    """@tool decorator must register function tools in the registry."""
    test_reg = ToolRegistry()

    @tool(
        name="sum_numbers",
        description="Add two numbers",
        args_schema=CustomArgs,
        risk_level="read",
        registry=test_reg,
    )
    async def sum_tool(args: CustomArgs, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, output=f"sum={args.lines}")

    assert test_reg.get("sum_numbers") is not None
    assert test_reg.get("SUM_NUMBERS") is not None

    specs = test_reg.get_tool_specs()
    assert len(specs) == 1
    assert specs[0].name == "sum_numbers"

    res = await sum_tool.run({"path": "a", "lines": 42})
    assert res.ok is True
    assert res.output == "sum=42"


def test_default_registry_contains_echo() -> None:
    """Default registry must contain the demo echo tool."""
    assert default_registry.get("echo") is not None


# --- Protocol and Parser Tests ---


def test_parse_native_tool_calls() -> None:
    """Native parser must extract tool calls from Message."""
    msg = Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="c1", name="echo", arguments={"message": "hi"})],
    )
    calls = parse_native_tool_calls(msg)
    assert len(calls) == 1
    assert calls[0].name == "echo"
    assert calls[0].arguments == {"message": "hi"}


def test_parse_fallback_tool_calls_clean() -> None:
    """Fallback parser must extract standard <tool_call> JSON."""
    raw = '<tool_call>{"name": "echo", "arguments": {"message": "hello"}}</tool_call>'
    calls = parse_fallback_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0].name == "echo"
    assert calls[0].arguments == {"message": "hello"}


def test_parse_fallback_tool_calls_code_fences() -> None:
    """Fallback parser must strip Markdown code fences inside <tool_call>."""
    raw = """
    Here is the requested action:
    <tool_call>
    ```json
    {
      "name": "echo",
      "arguments": {
        "message": "fenced"
      }
    }
    ```
    </tool_call>
    """
    calls = parse_fallback_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0].name == "echo"
    assert calls[0].arguments == {"message": "fenced"}


def test_parse_fallback_tool_calls_trailing_commas() -> None:
    """Fallback parser must tolerate trailing commas in dictionaries and arrays."""
    raw = """
    <tool_call>
    {
      "name": "echo",
      "arguments": {
        "message": "trailing comma",
        "tags": ["a", "b",],
      },
    }
    </tool_call>
    """
    calls = parse_fallback_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0].name == "echo"
    assert calls[0].arguments["message"] == "trailing comma"
    assert calls[0].arguments["tags"] == ["a", "b"]


def test_parse_fallback_tool_calls_single_quotes_and_python_literals() -> None:
    """Fallback parser must tolerate single quotes and Python True/False/None."""
    raw = (
        "<tool_call>{'name': 'echo', 'arguments': "
        "{'message': 'quotes', 'active': True, 'val': None}}</tool_call>"
    )
    calls = parse_fallback_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0].name == "echo"
    assert calls[0].arguments["message"] == "quotes"
    assert calls[0].arguments["active"] is True
    assert calls[0].arguments["val"] is None


def test_parse_fallback_multiple_tool_calls() -> None:
    """Fallback parser must parse multiple <tool_call> blocks in one response."""
    raw = """
    <tool_call>{"name": "echo", "arguments": {"message": "first"}}</tool_call>
    Some explanation between calls...
    <tool_call>{"name": "echo", "arguments": {"message": "second"}}</tool_call>
    """
    calls = parse_fallback_tool_calls(raw)
    assert len(calls) == 2
    assert calls[0].arguments["message"] == "first"
    assert calls[1].arguments["message"] == "second"


def test_parse_fallback_markdown_json_without_tag() -> None:
    """Fallback parser must detect markdown ```json tool call if model omits <tool_call> tag."""
    raw = """
    ```json
    {
      "name": "echo",
      "arguments": {
        "message": "untagged markdown"
      }
    }
    ```
    """
    calls = parse_fallback_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0].name == "echo"
    assert calls[0].arguments["message"] == "untagged markdown"


def test_get_tool_protocol_for_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_tool_protocol_for_model must select protocol from capability cache."""
    cap_file = tmp_path / "capabilities.json"
    save_capability("native-model", "native", path=cap_file)
    save_capability("fallback-model", "json_fallback", path=cap_file)
    monkeypatch.setattr("lathe.models.capabilities.get_capabilities_file_path", lambda: cap_file)

    assert get_tool_protocol_for_model("native-model") == "native"
    assert get_tool_protocol_for_model("fallback-model") == "fallback"
    assert get_tool_protocol_for_model("unknown-model") == "fallback"


def test_build_fallback_system_prompt() -> None:
    """build_fallback_system_prompt must include tool specifications and instructions."""
    echo = EchoTool()
    prompt = build_fallback_system_prompt([echo.to_tool_spec()])
    assert "<tool_call>" in prompt
    assert '"name": "echo"' in prompt
