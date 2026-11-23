"""Unit tests for MCP client, tool wrapping, and risk inference."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lathe.config import LatheConfig, McpConfig, McpServerConfig
from lathe.memory.mcp import McpTool, StdioMcpClient, load_mcp_tools
from lathe.tools.base import ToolContext


def test_mcp_tool_infer_risk():
    """Verify heuristics mapping tool name to Lathe RiskLevel."""
    client = MagicMock(spec=StdioMcpClient)

    read_schema = {"name": "get_file_info", "description": "Get file details"}
    write_schema = {"name": "create_repository", "description": "Create repo"}
    exec_schema = {"name": "run_script", "description": "Run script"}

    t_read = McpTool(server_name="test", tool_schema=read_schema, client=client)
    t_write = McpTool(server_name="test", tool_schema=write_schema, client=client)
    t_exec = McpTool(server_name="test", tool_schema=exec_schema, client=client)

    assert t_read.risk_level == "read"
    assert t_write.risk_level == "write"
    assert t_exec.risk_level == "execute"


def test_mcp_tool_schema_generation():
    """Converts MCP JSON Schema inputSchema to Pydantic args_schema."""
    client = MagicMock(spec=StdioMcpClient)
    schema = {
        "name": "search_entries",
        "description": "Search items",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    }
    tool = McpTool(server_name="mock_srv", tool_schema=schema, client=client)
    spec = tool.to_tool_spec()

    assert spec.name == "mcp__mock_srv__search_entries"
    assert "query" in spec.parameters["properties"]
    assert "limit" in spec.parameters["properties"]


@pytest.mark.asyncio
async def test_mcp_tool_execution():
    """Tool execution calls client.call_tool and wraps result in ToolResult."""
    client = MagicMock(spec=StdioMcpClient)
    client.start.return_value = True
    client.call_tool.return_value = "Result content from MCP"

    schema = {"name": "fetch_data", "description": "Fetch data"}
    tool = McpTool(server_name="db", tool_schema=schema, client=client)

    ctx = ToolContext()
    result = await tool.run({"arg": "val"}, ctx=ctx)

    assert result.ok is True
    assert result.output == "Result content from MCP"
    client.call_tool.assert_called_once_with("fetch_data", {"arg": "val"})


def test_load_mcp_tools_disabled():
    """load_mcp_tools returns empty list when MCP is disabled."""
    cfg = LatheConfig(
        mcp=McpConfig(
            enabled=False,
            servers={"gh": McpServerConfig(command="echo")},
        )
    )
    tools = load_mcp_tools(cfg)
    assert tools == []
