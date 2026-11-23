"""Memory system managing project instructions (LATHE.md), session persistence,
custom commands, and MCP tools.
"""

from dataclasses import dataclass, field
from typing import Any

from lathe.memory.commands import CustomCommand, CustomCommandManager
from lathe.memory.instructions import (
    append_to_lathe_md,
    explore_repository,
    generate_initial_lathe_md,
    get_global_lathe_md_path,
    get_local_lathe_md_path,
    load_project_instructions,
)
from lathe.memory.mcp import McpTool, StdioMcpClient, load_mcp_tools
from lathe.memory.sessions import SessionData, SessionInfo, SessionManager


@dataclass
class SessionMemory:
    """Stores short-term execution history and compressed repository context."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    ast_cache: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "CustomCommand",
    "CustomCommandManager",
    "McpTool",
    "SessionData",
    "SessionInfo",
    "SessionManager",
    "SessionMemory",
    "StdioMcpClient",
    "append_to_lathe_md",
    "explore_repository",
    "generate_initial_lathe_md",
    "get_global_lathe_md_path",
    "get_local_lathe_md_path",
    "load_mcp_tools",
    "load_project_instructions",
]
