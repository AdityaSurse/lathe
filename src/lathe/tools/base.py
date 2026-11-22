"""Base tool abstractions, execution results, context, and argument validation."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from lathe.llm.types import ToolSpec

RiskLevel = Literal["read", "write", "execute", "network"]


class ToolResult(BaseModel):
    """Result of a tool execution returned to the agent."""

    ok: bool = Field(description="Whether the tool execution succeeded.")
    output: str = Field(
        default="",
        description="Textual standard output or content produced by the tool.",
    )
    error: str | None = Field(default=None, description="Error message if execution failed.")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured execution metadata (e.g. diff stats, exit code).",
    )


class ToolContext(BaseModel):
    """Execution context provided to tools during runtime."""

    model_config = {"arbitrary_types_allowed": True}

    workspace_root: Path = Field(
        default_factory=Path.cwd,
        description="Root directory of the workspace.",
    )
    max_output_length: int = Field(
        default=8000,
        description="Maximum character limit for output before truncation.",
    )
    permission_engine: Any = Field(
        default=None,
        description="Optional PermissionEngine instance to enforce authorization policies.",
    )
    checkpoint_manager: Any = Field(
        default=None,
        description="Optional CheckpointManager instance for working tree snapshots.",
    )

    def get_workspace(self) -> Any:
        """Return a Workspace boundary instance bound to the context workspace root."""
        from lathe.safety.workspace import Workspace

        return Workspace(self.workspace_root)


def truncate_output(text: str, max_chars: int = 8000) -> str:
    """Truncate output exceeding max_chars and append a marker with remaining line count."""
    if len(text) <= max_chars:
        return text

    truncated_portion = text[:max_chars]
    remaining_text = text[max_chars:]
    remaining_lines = remaining_text.count("\n")

    if remaining_lines > 0:
        return f"{truncated_portion}\n... [truncated, {remaining_lines} more lines]"
    chars_left = len(remaining_text)
    return f"{truncated_portion}\n... [truncated, {chars_left} more characters]"


class Tool(ABC):
    """Abstract base class for all Lathe agent tools."""

    name: str
    description: str
    args_schema: type[BaseModel]
    risk_level: RiskLevel = "read"

    def to_tool_spec(self) -> ToolSpec:
        """Generate JSON Schema specification matching LLM tool calling format."""
        schema = self.args_schema.model_json_schema()
        # Clean up schema metadata not needed by LLM function specs
        cleaned_schema = {
            "type": "object",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }
        if "description" in schema:
            cleaned_schema["description"] = schema["description"]

        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=cleaned_schema,
        )

    async def run(
        self,
        args: dict[str, Any] | BaseModel,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        """Validate arguments and execute the tool, returning structured ToolResult."""
        context = ctx or ToolContext()

        # Validate arguments against Pydantic schema
        if isinstance(args, self.args_schema):
            validated_args = args
        elif isinstance(args, dict):
            try:
                validated_args = self.args_schema.model_validate(args)
            except ValidationError as err:
                error_messages: list[str] = []
                for e in err.errors():
                    field_name = ".".join(str(loc) for loc in e["loc"]) if e["loc"] else "value"
                    error_messages.append(f"field '{field_name}' {e['msg']}")
                formatted_error = (
                    f"Invalid arguments for tool '{self.name}': "
                    + ", ".join(error_messages)
                    + ". Please adjust the arguments and retry."
                )
                return ToolResult(ok=False, output="", error=formatted_error)
        else:
            return ToolResult(
                ok=False,
                output="",
                error=f"Invalid arguments type: expected dict or {self.args_schema.__name__}.",
            )

        # Check permissions if an engine is configured in context
        if context.permission_engine is not None:
            raw_dict = (
                validated_args.model_dump()
                if hasattr(validated_args, "model_dump")
                else (args if isinstance(args, dict) else {})
            )
            perm_result = context.permission_engine.check_permission(self, raw_dict, context)
            if perm_result.is_denied:
                denied_msg = (
                    perm_result.message_to_model
                    or perm_result.reason
                    or f"Permission denied for tool '{self.name}'."
                )
                return ToolResult(
                    ok=False,
                    output="",
                    error=denied_msg,
                    metadata={"permission_denied": True, "reason": perm_result.reason},
                )
            if perm_result.edited_command and hasattr(validated_args, "command"):
                validated_args.command = perm_result.edited_command

        # Checkpoint snapshot before file modifications or shell execution
        if context.checkpoint_manager is not None and self.risk_level in ("write", "execute"):
            try:
                target_desc = f"Before {self.name}"
                if hasattr(validated_args, "path"):
                    target_desc += f"({validated_args.path})"
                elif hasattr(validated_args, "command"):
                    cmd_preview = str(validated_args.command)[:30]
                    target_desc += f"({cmd_preview})"
                context.checkpoint_manager.create_checkpoint(target_desc)
            except Exception:
                pass

        # Execute tool logic with exception protection
        try:
            result = await self._execute(validated_args, context)
        except Exception as exc:
            return ToolResult(
                ok=False,
                output="",
                error=f"Tool '{self.name}' execution failed: {exc}",
            )

        # Apply output truncation if necessary
        truncated_out = truncate_output(result.output, max_chars=context.max_output_length)
        result.output = truncated_out
        return result

    @abstractmethod
    async def _execute(self, args: Any, ctx: ToolContext) -> ToolResult:
        """Implementation logic executed by subclasses."""
        ...


# --- Demo Echo Tool ---


class EchoArgs(BaseModel):
    """Arguments for the demo echo tool."""

    message: str = Field(description="The textual message to echo back.")


class EchoTool(Tool):
    """Demo tool that echoes the input message back."""

    name = "echo"
    description = "Echoes the provided message back to the caller."
    args_schema = EchoArgs
    risk_level = "read"

    async def _execute(self, args: EchoArgs, ctx: ToolContext) -> ToolResult:
        """Echo the input message."""
        return ToolResult(ok=True, output=args.message)
