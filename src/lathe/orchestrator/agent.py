"""Core agent loop coordinating LLM reasoning, tool execution, safety, and event dispatch."""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from rich.console import Console

from lathe.config import LatheConfig, load_config
from lathe.llm.base import LLMClient, LLMError
from lathe.llm.factory import get_client
from lathe.llm.types import Message, ToolCall, ToolSpec
from lathe.orchestrator.events import (
    AgentHaltEvent,
    DiffEvent,
    EventBus,
    FinalAnswerEvent,
    NudgeEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from lathe.prompts import get_agent_system_prompt
from lathe.safety.checkpoints import CheckpointManager, get_checkpoint_manager
from lathe.safety.permissions import PermissionEngine, PermissionMode
from lathe.tools.base import ToolContext, ToolResult
from lathe.tools.protocol import (
    build_fallback_system_prompt,
    get_tool_protocol_for_model,
    parse_fallback_tool_calls,
)
from lathe.tools.registry import ToolRegistry, default_registry


class Agent:
    """Core autonomous coding agent loop executing multi-step tasks."""

    def __init__(
        self,
        config: LatheConfig | None = None,
        client: LLMClient | None = None,
        tools: ToolRegistry | None = None,
        permission_engine: PermissionEngine | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        workspace_root: Path | None = None,
        event_bus: EventBus | None = None,
        max_steps: int | None = None,
        console: Console | None = None,
    ) -> None:
        self.config = config or load_config(require_secrets=False)
        self.workspace_root = workspace_root or Path.cwd()
        self.console = console or Console()
        self.tools = tools or default_registry
        self.event_bus = event_bus or EventBus()
        self.max_steps: int = int(
            max_steps or getattr(self.config.settings, "max_agent_steps", 25) or 25
        )

        # Initialize or resolve LLM client (coder role)
        if client is not None:
            self.client = client
        else:
            self.client = get_client("coder", config=self.config)

        # Initialize safety and checkpoints
        self.permission_engine = permission_engine
        self.checkpoint_manager = checkpoint_manager

        # Internal call history for loop detection: list of "tool_name:sorted_json_args"
        self._call_history: list[str] = []
        self._edited_files: set[str] = set()

    def _extract_mentioned_files(self, task: str) -> list[str]:
        """Extract file paths explicitly referenced in task prompt (e.g. @file)."""
        mentioned: list[str] = []
        for match in re.findall(r"@([^\s,]+)", task):
            mentioned.append(match.strip())
        for match in re.findall(r"\b[\w\./\-]+\.(?:py|js|ts|tsx|go|rs|java|c|cpp|h)\b", task):
            mentioned.append(match.strip())
        return mentioned

    def _get_tool_context(self) -> ToolContext:
        """Construct a ToolContext with active safety and checkpoint bindings."""
        return ToolContext(
            workspace_root=self.workspace_root,
            permission_engine=self.permission_engine,
            checkpoint_manager=self.checkpoint_manager,
        )

    def _build_system_prompt(
        self,
        task: str,
        tool_specs: list[ToolSpec],
        protocol: str,
    ) -> str:
        """Construct system prompt enriched with fallback tool instructions and dynamic repomap."""
        base_prompt = get_agent_system_prompt()
        if protocol == "fallback":
            fallback_instructions = build_fallback_system_prompt(tool_specs)
            base_prompt = f"{base_prompt}\n\n{fallback_instructions}"

        try:
            from lathe.context.repomap import RepoMap

            repomap_budget = getattr(self.config.settings, "repomap_token_budget", 2048)
            rm = RepoMap(workspace_root=self.workspace_root, token_budget=repomap_budget)
            mentioned = self._extract_mentioned_files(task)
            repo_map_text = rm.get_repo_map(
                task=task,
                mentioned_files=mentioned,
                edited_files=list(self._edited_files),
            )
            if repo_map_text:
                header = (
                    "Below is a map of the most relevant files and symbol "
                    "signatures in this codebase:\n\n"
                )
                return f"{base_prompt}\n\n# Repository Map\n{header}{repo_map_text}"
        except Exception:
            pass

        return base_prompt

    def _build_initial_messages(
        self,
        task: str,
        tool_specs: list[ToolSpec],
        protocol: str,
    ) -> list[Message]:
        """Construct system prompt and initial user message."""
        system_content = self._build_system_prompt(task, tool_specs, protocol)
        return [
            Message(role="system", content=system_content),
            Message(role="user", content=task),
        ]

    async def run(
        self,
        task: str,
        messages: list[Message] | None = None,
    ) -> str:
        """Execute the autonomous agent loop until task completion or step limit."""
        model_name = self.client.role_config.model
        protocol = get_tool_protocol_for_model(model_name)
        tool_specs = self.tools.get_tool_specs()
        ctx = self._get_tool_context()

        # Initialize or append to conversation history
        if messages is None:
            conversation_messages = self._build_initial_messages(task, tool_specs, protocol)
        else:
            conversation_messages = messages
            if not conversation_messages:
                conversation_messages.extend(
                    self._build_initial_messages(task, tool_specs, protocol)
                )
            else:
                conversation_messages.append(Message(role="user", content=task))

        step_idx = 0

        while step_idx < self.max_steps:
            step_idx += 1

            # Inject / refresh the repository map in the system prompt each turn
            if conversation_messages and conversation_messages[0].role == "system":
                conversation_messages[0].content = self._build_system_prompt(
                    task, tool_specs, protocol
                )

            # 1. Query LLM
            content_parts: list[str] = []
            native_tool_calls: list[ToolCall] = []

            try:
                # Provide tool specs if native protocol is supported
                passed_tools = tool_specs if protocol == "native" else None
                async for chunk in self.client.chat(
                    conversation_messages, tools=passed_tools, stream=True
                ):
                    if chunk.delta:
                        content_parts.append(chunk.delta)
                        await self.event_bus.emit(
                            ThinkingEvent(
                                content="".join(content_parts),
                                delta=chunk.delta,
                                step_index=step_idx,
                            )
                        )
                    if chunk.tool_call_delta:
                        native_tool_calls.append(chunk.tool_call_delta)
            except LLMError as err:
                err_msg = f"LLM generation failed: {err}"
                await self.event_bus.emit(AgentHaltEvent(reason=err_msg, total_steps=step_idx))
                return err_msg

            full_content = "".join(content_parts).strip()

            # 2. Extract tool calls according to protocol
            tool_calls: list[ToolCall] = []
            if native_tool_calls or protocol == "native":
                tool_calls = native_tool_calls
            else:
                tool_calls = parse_fallback_tool_calls(full_content)

            # 3. If no tool calls -> Final Answer reached!
            if not tool_calls:
                conversation_messages.append(Message(role="assistant", content=full_content))
                await self.event_bus.emit(
                    FinalAnswerEvent(
                        content=full_content,
                        total_steps=step_idx,
                        step_index=step_idx,
                    )
                )
                return full_content

            # Emit thoughts/reasoning preceding tool calls if present
            thinking_text = re.sub(
                r"<tool_call>.*?</tool_call>", "", full_content, flags=re.DOTALL
            ).strip()
            if thinking_text and protocol == "fallback":
                await self.event_bus.emit(
                    ThinkingEvent(
                        content=thinking_text,
                        delta=None,
                        step_index=step_idx,
                    )
                )

            # 4. Loop Detection Check
            # Check repetition: 3 times -> nudge, 5 times -> stop
            loop_halt_reason: str | None = None
            for call in tool_calls:
                call_sig = f"{call.name.lower()}:{json.dumps(call.arguments, sort_keys=True)}"
                rep_count = self._call_history.count(call_sig)

                if rep_count == 2:
                    # 3rd occurrence
                    nudge_text = "You are repeating yourself, try a different approach."
                    await self.event_bus.emit(
                        NudgeEvent(
                            message=nudge_text,
                            repetition_count=3,
                            tool_name=call.name,
                            step_index=step_idx,
                        )
                    )
                    nudge_content = (
                        f"System notice: {nudge_text} "
                        f"(Tool '{call.name}' called with identical arguments)."
                    )
                    conversation_messages.append(
                        Message(
                            role="user",
                            content=nudge_content,
                        )
                    )
                elif rep_count >= 4:
                    # 5th occurrence -> Stop!
                    loop_halt_reason = (
                        f"Loop detected: tool '{call.name}' called 5 times "
                        "with identical arguments."
                    )
                    await self.event_bus.emit(
                        NudgeEvent(
                            message=loop_halt_reason,
                            repetition_count=5,
                            tool_name=call.name,
                            step_index=step_idx,
                        )
                    )
                    break

                self._call_history.append(call_sig)

            if loop_halt_reason:
                await self.event_bus.emit(
                    AgentHaltEvent(
                        reason=loop_halt_reason,
                        total_steps=step_idx,
                        step_index=step_idx,
                    )
                )
                await self.event_bus.emit(
                    FinalAnswerEvent(
                        content=loop_halt_reason,
                        total_steps=step_idx,
                        step_index=step_idx,
                    )
                )
                return loop_halt_reason

            # Append the assistant's message to conversation
            if protocol == "native":
                conversation_messages.append(
                    Message(role="assistant", content=full_content, tool_calls=tool_calls)
                )
            else:
                conversation_messages.append(Message(role="assistant", content=full_content))

            # 5. Tool Execution: Parallel for multiple READ-only, Sequential otherwise
            def _is_read_tool(t_name: str) -> bool:
                tool_obj = self.tools.get(t_name)
                return tool_obj is not None and tool_obj.risk_level == "read"

            all_read_only = len(tool_calls) > 1 and all(_is_read_tool(c.name) for c in tool_calls)

            async def _run_tool(
                call_item: ToolCall, current_step: int
            ) -> tuple[ToolCall, ToolResult]:
                tool_instance = self.tools.get(call_item.name)
                t_start = time.perf_counter()

                if tool_instance is None:
                    res = ToolResult(
                        ok=False,
                        output="",
                        error=f"Tool '{call_item.name}' is not recognized in registry.",
                    )
                    duration = (time.perf_counter() - t_start) * 1000.0
                    await self.event_bus.emit(
                        ToolEndEvent(
                            tool_id=call_item.id,
                            tool_name=call_item.name,
                            arguments=call_item.arguments,
                            result=res,
                            duration_ms=duration,
                            step_index=current_step,
                        )
                    )
                    return call_item, res

                await self.event_bus.emit(
                    ToolStartEvent(
                        tool_id=call_item.id,
                        tool_name=call_item.name,
                        arguments=call_item.arguments,
                        risk_level=tool_instance.risk_level,
                        step_index=current_step,
                    )
                )

                # Tool.run handles permissions and checkpoint snapshots internally
                res = await tool_instance.run(call_item.arguments, ctx=ctx)
                duration = (time.perf_counter() - t_start) * 1000.0

                if res.ok and call_item.name in ("edit_file", "write_file"):
                    edited_path = str(call_item.arguments.get("path", ""))
                    if edited_path:
                        self._edited_files.add(edited_path)

                # Check if edit tool produced a unified diff
                if call_item.name == "edit_file" and res.metadata.get("diff"):
                    await self.event_bus.emit(
                        DiffEvent(
                            path=str(call_item.arguments.get("path", "")),
                            diff=res.metadata["diff"],
                            summary=res.output,
                            step_index=current_step,
                        )
                    )

                await self.event_bus.emit(
                    ToolEndEvent(
                        tool_id=call_item.id,
                        tool_name=call_item.name,
                        arguments=call_item.arguments,
                        result=res,
                        duration_ms=duration,
                        step_index=current_step,
                    )
                )
                return call_item, res

            if all_read_only:
                # Concurrent read execution
                tool_results = await asyncio.gather(
                    *[_run_tool(call, step_idx) for call in tool_calls]
                )
            else:
                # Sequential execution
                tool_results = []
                for call in tool_calls:
                    r = await _run_tool(call, step_idx)
                    tool_results.append(r)

            # Append results to conversation
            for call, result in tool_results:
                result_payload = result.output if result.ok else (result.error or "Tool failed.")
                if protocol == "native":
                    conversation_messages.append(
                        Message(
                            role="tool",
                            tool_call_id=call.id or call.name,
                            content=result_payload,
                        )
                    )
                else:
                    response_block = (
                        f'<tool_response tool="{call.name}">\n{result_payload}\n</tool_response>'
                    )
                    conversation_messages.append(
                        Message(
                            role="user",
                            content=response_block,
                        )
                    )

        # Exceeded max agent steps
        halt_reason = f"Agent stopped: reached maximum allowed steps ({self.max_steps})."
        await self.event_bus.emit(
            AgentHaltEvent(reason=halt_reason, total_steps=step_idx, step_index=step_idx)
        )
        await self.event_bus.emit(
            FinalAnswerEvent(content=halt_reason, total_steps=step_idx, step_index=step_idx)
        )
        return halt_reason


def run_one_shot(
    task: str,
    auto: bool = False,
    yolo: bool = False,
    config: LatheConfig | None = None,
) -> str:
    """Run agent in one-shot mode (`lathe "task"`) and return final result."""
    from lathe.ui.agent_view import TerminalAgentUI

    active_config = config or load_config(require_secrets=False)
    console = Console()
    workspace = Path.cwd()

    # Determine permission mode
    mode = PermissionMode.DEFAULT
    if yolo:
        mode = PermissionMode.YOLO
    elif auto:
        mode = PermissionMode.AUTO

    permission_engine = PermissionEngine(workspace, mode=mode, console=console)
    if yolo:
        permission_engine.emit_yolo_warning()

    checkpoint_mgr = get_checkpoint_manager(workspace, prompt_init=False)

    agent = Agent(
        config=active_config,
        permission_engine=permission_engine,
        checkpoint_manager=checkpoint_mgr,
        workspace_root=workspace,
        console=console,
    )

    # Attach terminal UI listener to event bus
    ui = TerminalAgentUI(console=console)
    ui.attach(agent.event_bus)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(agent.run(task))
    finally:
        loop.close()
