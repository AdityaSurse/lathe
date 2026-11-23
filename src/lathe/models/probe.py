"""Probe model tool calling capabilities and update cache."""

import json
import re

import httpx
from rich.console import Console

from lathe.models.capabilities import CapabilityProtocol, save_capability

TOOL_TEST_SPEC = {
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two integers",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
    },
}

FALLBACK_PROMPT = (
    "You have access to tools. When you need to call a tool, "
    "output a Markdown JSON code block in this format:\n"
    "```json\n"
    '{"name": "tool_name", "arguments": {"param": value}}\n'
    "```\n"
    "Available tools:\n"
    "- add(a: integer, b: integer): Add two numbers\n\n"
    "Please execute this request: call add(a=2,b=3)"
)


def _contains_valid_add_call(text: str) -> bool:
    """Check if text contains a valid add(a=2, b=3) call in json or text format."""
    if "add" not in text:
        return False
    m = re.search(r"\{.*?\"name\"\s*:\s*\"add\".*?\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if data.get("name") == "add":
                return True
        except Exception:
            pass
    return bool('"add"' in text and ('"a"' in text or '"arguments"' in text))


async def probe_model(
    model: str,
    base_url: str = "http://localhost:11434",
    client: httpx.AsyncClient | None = None,
    console: Console | None = None,
) -> CapabilityProtocol:
    """Probe whether model supports native tool calls, JSON fallback, or neither."""
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

    try:
        native_payload = {
            "model": model,
            "messages": [{"role": "user", "content": "call add(a=2,b=3)"}],
            "tools": [TOOL_TEST_SPEC],
            "stream": False,
        }

        try:
            resp = await http_client.post(
                f"{base_url.rstrip('/')}/api/chat",
                json=native_payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("message", {})
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    fn = tool_calls[0].get("function", {})
                    if fn.get("name") == "add":
                        save_capability(model, "native")
                        return "native"

                content = msg.get("content", "")
                if "add" in content and "{" in content and _contains_valid_add_call(content):
                    save_capability(model, "json_fallback")
                    return "json_fallback"
        except Exception:
            pass

        fallback_payload = {
            "model": model,
            "messages": [{"role": "user", "content": FALLBACK_PROMPT}],
            "stream": False,
        }

        try:
            resp = await http_client.post(
                f"{base_url.rstrip('/')}/api/chat",
                json=fallback_payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                if _contains_valid_add_call(content):
                    save_capability(model, "json_fallback")
                    return "json_fallback"
        except Exception:
            pass

        save_capability(model, "none")
        return "none"

    finally:
        if owns_client:
            await http_client.aclose()
