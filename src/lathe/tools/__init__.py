"""Tool framework providing registry, schemas, execution sandboxing, and protocol parsing."""

from lathe.tools.base import (
    EchoArgs,
    EchoTool,
    RiskLevel,
    Tool,
    ToolContext,
    ToolResult,
    truncate_output,
)
from lathe.tools.protocol import (
    FALLBACK_TOOL_SYSTEM_PROMPT,
    ToolProtocol,
    build_fallback_system_prompt,
    get_tool_protocol_for_model,
    parse_fallback_tool_calls,
    parse_native_tool_calls,
)
from lathe.tools.registry import (
    FunctionTool,
    ToolRegistry,
    default_registry,
    tool,
)

__all__ = [
    "FALLBACK_TOOL_SYSTEM_PROMPT",
    "EchoArgs",
    "EchoTool",
    "FunctionTool",
    "RiskLevel",
    "Tool",
    "ToolContext",
    "ToolProtocol",
    "ToolRegistry",
    "ToolResult",
    "build_fallback_system_prompt",
    "default_registry",
    "get_tool_protocol_for_model",
    "parse_fallback_tool_calls",
    "parse_native_tool_calls",
    "tool",
    "truncate_output",
]
