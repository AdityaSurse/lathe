"""Tool-calling protocols: native provider calls and robust <tool_call> fallback parsing."""

import ast
import json
import re
from typing import Any, Literal

from lathe.llm.types import Message, ToolCall, ToolSpec
from lathe.models.capabilities import get_capability

ToolProtocol = Literal["native", "fallback"]

FALLBACK_TOOL_SYSTEM_PROMPT = """You have access to the following tools:
{tool_specs}

To call a tool, respond with a <tool_call> block containing a JSON object:
<tool_call>
{{"name": "tool_name", "arguments": {{"param": "value"}}}}
</tool_call>

You may call multiple tools sequentially by providing multiple <tool_call> blocks."""


def get_tool_protocol_for_model(model: str) -> ToolProtocol:
    """Determine tool-call protocol based on cached model capabilities."""
    cap = get_capability(model)
    if cap and cap.get("tool_protocol") == "native":
        return "native"
    return "fallback"


def build_fallback_system_prompt(tools: list[ToolSpec]) -> str:
    """Generate system prompt instructions for models using the <tool_call> fallback protocol."""
    specs_json = json.dumps([t.model_dump() for t in tools], indent=2)
    return FALLBACK_TOOL_SYSTEM_PROMPT.format(tool_specs=specs_json)


def parse_native_tool_calls(message: Message) -> list[ToolCall]:
    """Extract tool calls emitted via native provider structured tool calling."""
    return message.tool_calls or []


def _clean_and_parse_json(raw: str) -> dict[str, Any] | None:
    """Parse JSON tolerating code fences, trailing commas, single quotes, and Python literals."""
    text = raw.strip()

    # 1. Strip Markdown code fences if present (e.g. ```json ... ```)
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # 2. Fast path: standard json.loads
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 3. Clean trailing commas in dicts and lists: e.g. {"a": 1,} -> {"a": 1}
    no_trailing_commas = re.sub(r",\s*([\]}])", r"\1", text)
    try:
        data = json.loads(no_trailing_commas)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 4. Handle Python-style literals (single quotes, True/False/None) via ast.literal_eval
    try:
        val = ast.literal_eval(no_trailing_commas)
        if isinstance(val, dict):
            return val
    except Exception:
        pass

    # 5. Fix single quotes to double quotes for keys and string values
    single_quote_fixed = re.sub(r"'([^']*)'", r'"\1"', no_trailing_commas)
    single_quote_fixed = re.sub(r":\s*True\b", ": true", single_quote_fixed)
    single_quote_fixed = re.sub(r":\s*False\b", ": false", single_quote_fixed)
    single_quote_fixed = re.sub(r":\s*None\b", ": null", single_quote_fixed)
    try:
        data = json.loads(single_quote_fixed)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return None


def parse_fallback_tool_calls(text: str) -> list[ToolCall]:
    """Extract and parse <tool_call> blocks from assistant output."""
    tool_calls: list[ToolCall] = []

    # 1. Match <tool_call>...</tool_call> (or unclosed <tool_call>...$)
    matches = re.findall(r"<tool_call>(.*?)(?:</tool_call>|$)", text, re.DOTALL)

    for idx, raw_block in enumerate(matches):
        cleaned = raw_block.strip()
        if not cleaned:
            continue
        parsed = _clean_and_parse_json(cleaned)
        if parsed and isinstance(parsed, dict):
            name = parsed.get("name")
            if name and isinstance(name, str):
                args = parsed.get("arguments", {})
                if not isinstance(args, dict):
                    args = {"value": args}
                tool_calls.append(
                    ToolCall(
                        id=f"call_{idx}",
                        name=name,
                        arguments=args,
                    )
                )

    # 2. If no <tool_call> tags matched, check for markdown ```json blocks
    if not tool_calls and "name" in text and "arguments" in text:
        json_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        for idx, block in enumerate(json_blocks):
            parsed = _clean_and_parse_json(block)
            if parsed and isinstance(parsed, dict) and "name" in parsed:
                name = parsed["name"]
                args = parsed.get("arguments", {})
                if not isinstance(args, dict):
                    args = {"value": args}
                tool_calls.append(
                    ToolCall(
                        id=f"call_{idx}",
                        name=name,
                        arguments=args,
                    )
                )

    return tool_calls
