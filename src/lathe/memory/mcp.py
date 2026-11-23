"""Model Context Protocol (MCP) stdio client and tool bridge (Phase 22)."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, create_model

from lathe.config import LatheConfig
from lathe.tools.base import RiskLevel, Tool, ToolContext, ToolResult


class McpToolArgs(BaseModel):
    """Fallback arguments model for dynamically registered MCP tools."""

    model_config = {"extra": "allow"}


class StdioMcpClient:
    """Lightweight pure-Python stdio JSON-RPC 2.0 client for MCP servers."""

    def __init__(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: Path | str | None = None,
    ) -> None:
        self.server_name = server_name
        self.command = command
        self.args = list(args) if args else []
        self.env = env or {}
        self.cwd = Path(cwd) if cwd else Path.cwd()
        self.process: subprocess.Popen[str] | None = None
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def start(self) -> bool:
        """Launch the MCP server process and establish JSON-RPC session."""
        if self.process is not None and self.process.poll() is None:
            return True

        merged_env = os.environ.copy()
        merged_env.update(self.env)

        full_cmd = [self.command] + self.args
        try:
            self.process = subprocess.Popen(
                full_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.cwd),
                env=merged_env,
                text=True,
                bufsize=1,
            )
            return self._initialize()
        except Exception:
            self.process = None
            return False

    def _send(self, payload: dict[str, Any]) -> None:
        """Send a single JSON-RPC line to server stdin."""
        if self.process is None or self.process.stdin is None:
            raise RuntimeError(f"MCP server '{self.server_name}' process is not running.")
        line = json.dumps(payload) + "\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()

    def _receive(self) -> dict[str, Any]:
        """Read a single JSON-RPC response line from server stdout."""
        if self.process is None or self.process.stdout is None:
            raise RuntimeError(f"MCP server '{self.server_name}' process is not running.")
        line = self.process.stdout.readline()
        if not line:
            err = ""
            if self.process.stderr:
                err = self.process.stderr.read()
            raise RuntimeError(f"MCP server '{self.server_name}' closed stdout: {err}")
        raw_data = json.loads(line.strip())
        return cast(dict[str, Any], raw_data if isinstance(raw_data, dict) else {})

    def _initialize(self) -> bool:
        """Perform MCP initialization handshake."""
        init_id = self._next_id()
        init_req = {
            "jsonrpc": "2.0",
            "id": init_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "lathe", "version": "0.1.0"},
            },
        }
        try:
            self._send(init_req)
            resp = self._receive()
            if "error" in resp:
                return False

            # Send initialized notification
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            return True
        except Exception:
            return False

    def list_tools(self) -> list[dict[str, Any]]:
        """Query the MCP server for available tool schemas via tools/list."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        try:
            self._send(req)
            resp = self._receive()
            if "error" in resp:
                return []
            result = resp.get("result", {})
            if isinstance(result, dict):
                tools = result.get("tools", [])
                if isinstance(tools, list):
                    return cast(list[dict[str, Any]], tools)
            return []
        except Exception:
            return []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool on the MCP server via tools/call and return output text."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
        }
        self._send(req)
        resp = self._receive()
        if "error" in resp:
            err = resp["error"]
            raise RuntimeError(f"MCP Error ({err.get('code')}): {err.get('message')}")

        result = resp.get("result", {})
        content = result.get("content", [])

        # Content is typically a list of content parts e.g. [{"type": "text", "text": "..."}]
        if isinstance(content, list):
            texts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(str(item.get("text", "")))
                else:
                    texts.append(json.dumps(item))
            return "\n".join(texts)
        if isinstance(result, dict) and "text" in result:
            return str(result["text"])
        return json.dumps(result)

    def close(self) -> None:
        """Terminate the server process cleanly."""
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:
                with contextlib.suppress(Exception):
                    self.process.kill()
            finally:
                self.process = None


class McpTool(Tool):
    """Lathe Tool bridge wrapping a remote Model Context Protocol (MCP) tool."""

    def __init__(
        self,
        server_name: str,
        tool_schema: dict[str, Any],
        client: StdioMcpClient,
    ) -> None:
        raw_name = tool_schema.get("name", "unnamed_tool")
        self.server_name = server_name
        self.mcp_tool_name = raw_name
        self.name = f"mcp__{server_name}__{raw_name}"
        self.description = (
            f"[MCP: {server_name}] "
            f"{tool_schema.get('description', f'Tool {raw_name} from {server_name} MCP server.')}"
        )
        self.client = client
        self.risk_level = self._infer_risk_level(raw_name)
        self.args_schema = self._build_args_schema(tool_schema.get("inputSchema"))

    def _infer_risk_level(self, name: str) -> RiskLevel:
        """Classify risk level from tool name heuristics."""
        lower = name.lower()
        read_prefixes = ("get_", "read_", "list_", "search_", "fetch_", "view_")
        if any(prefix in lower for prefix in read_prefixes):
            return "read"
        write_prefixes = ("write_", "edit_", "create_", "update_", "delete_", "remove_")
        if any(prefix in lower for prefix in write_prefixes):
            return "write"
        if any(prefix in lower for prefix in ("run_", "execute_", "eval_", "exec_", "shell_")):
            return "execute"
        return "execute"

    def _build_args_schema(self, input_schema: dict[str, Any] | None) -> type[BaseModel]:
        """Convert MCP inputSchema into a Pydantic argument model."""
        if not input_schema or not isinstance(input_schema, dict):
            return McpToolArgs

        properties = input_schema.get("properties", {})
        if not properties:
            return McpToolArgs

        fields: dict[str, Any] = {}
        type_mapping = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        required_set = set(input_schema.get("required", []))

        for prop_name, prop_meta in properties.items():
            if not isinstance(prop_meta, dict):
                fields[prop_name] = (Any, None)
                continue

            ptype_str = prop_meta.get("type", "string")
            py_type = type_mapping.get(ptype_str, Any)

            if prop_name in required_set:
                fields[prop_name] = (py_type, ...)
            else:
                default_val = prop_meta.get("default", None)
                fields[prop_name] = (py_type | None, default_val)

        try:
            return create_model(
                f"{self.server_name.capitalize()}_{self.mcp_tool_name}_Args",
                **fields,
            )
        except Exception:
            return McpToolArgs

    async def _execute(self, args: Any, ctx: ToolContext) -> ToolResult:
        """Execute the remote MCP tool via the stdio client."""
        kwargs: dict[str, Any] = (
            args.model_dump()
            if hasattr(args, "model_dump")
            else (args if isinstance(args, dict) else {})
        )
        try:
            if not self.client.start():
                return ToolResult(
                    ok=False,
                    output="",
                    error=f"Failed to start or connect to MCP server '{self.server_name}'.",
                )
            output = self.client.call_tool(self.mcp_tool_name, kwargs)
            return ToolResult(
                ok=True,
                output=output,
                error=None,
                metadata={"server": self.server_name, "tool": self.mcp_tool_name},
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                output="",
                error=f"MCP tool execution error on '{self.server_name}': {exc}",
            )


def load_mcp_tools(
    config: LatheConfig,
    workspace_root: Path | str | None = None,
    enabled_override: bool | None = None,
) -> list[Tool]:
    """Inspect config.mcp.servers and return initialized McpTool instances."""
    is_enabled = enabled_override if enabled_override is not None else config.mcp.enabled
    if not is_enabled or not config.mcp.servers:
        return []

    ws = Path(workspace_root).resolve() if workspace_root is not None else Path.cwd()
    tools: list[Tool] = []

    for name, s_cfg in config.mcp.servers.items():
        client = StdioMcpClient(
            server_name=name,
            command=s_cfg.command,
            args=s_cfg.args,
            env=s_cfg.env,
            cwd=ws,
        )
        if client.start():
            schemas = client.list_tools()
            for schema in schemas:
                tool = McpTool(server_name=name, tool_schema=schema, client=client)
                tools.append(tool)

    return tools
