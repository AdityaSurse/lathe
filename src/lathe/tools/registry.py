"""Tool registry and @tool decorator for managing agent workspace tools."""

from collections.abc import Callable, Coroutine
from typing import Any

from pydantic import BaseModel

from lathe.llm.types import ToolSpec
from lathe.tools.base import EchoTool, RiskLevel, Tool, ToolContext, ToolResult
from lathe.tools.edit import edit_file
from lathe.tools.files import glob, list_dir, read_file, write_file
from lathe.tools.git import git_commit, git_diff, git_log, git_status
from lathe.tools.search import grep_search, semantic_search
from lathe.tools.shell import run_shell


class FunctionTool(Tool):
    """Adapter wrapping an async function as a Tool instance."""

    def __init__(
        self,
        name: str,
        description: str,
        args_schema: type[BaseModel],
        handler: Callable[[Any, ToolContext], Coroutine[Any, Any, ToolResult]],
        risk_level: RiskLevel = "read",
    ) -> None:
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self.risk_level = risk_level
        self._handler = handler

    async def _execute(self, args: Any, ctx: ToolContext) -> ToolResult:
        return await self._handler(args, ctx)


class ToolRegistry:
    """Registry maintaining available workspace tools and their specifications."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool instance in the registry."""
        self._tools[tool.name.lower()] = tool

    def get(self, name: str) -> Tool | None:
        """Lookup tool by name (case-insensitive)."""
        return self._tools.get(name.lower())

    def list_tools(self) -> list[Tool]:
        """Return all registered tools sorted by name."""
        return sorted(self._tools.values(), key=lambda t: t.name)

    def get_tool_specs(self) -> list[ToolSpec]:
        """Export all registered tools as ToolSpec models for the LLM."""
        return [t.to_tool_spec() for t in self.list_tools()]


def tool(
    name: str,
    description: str,
    args_schema: type[BaseModel],
    risk_level: RiskLevel = "read",
    registry: ToolRegistry | None = None,
) -> Callable[[Callable[[Any, ToolContext], Coroutine[Any, Any, ToolResult]]], FunctionTool]:
    """Decorator to define and register a tool from an async function."""

    def decorator(
        func: Callable[[Any, ToolContext], Coroutine[Any, Any, ToolResult]],
    ) -> FunctionTool:
        tool_instance = FunctionTool(
            name=name,
            description=description,
            args_schema=args_schema,
            handler=func,
            risk_level=risk_level,
        )
        target_registry = registry or default_registry
        target_registry.register(tool_instance)
        return tool_instance

    return decorator


# Global default registry pre-seeded with built-in tools
default_registry = ToolRegistry()
default_registry.register(EchoTool())
default_registry.register(read_file)
default_registry.register(list_dir)
default_registry.register(glob)
default_registry.register(write_file)
default_registry.register(edit_file)
default_registry.register(run_shell)
default_registry.register(git_status)
default_registry.register(git_diff)
default_registry.register(git_log)
default_registry.register(git_commit)
default_registry.register(grep_search)
default_registry.register(semantic_search)
