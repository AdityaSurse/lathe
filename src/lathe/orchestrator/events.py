"""Typed event models and publish-subscribe event bus for the Lathe agent loop."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from lathe.tools.base import ToolResult


class BaseAgentEvent(BaseModel):
    """Base class for all events emitted during agent execution."""

    timestamp: datetime = Field(default_factory=datetime.now)
    step_index: int = Field(default=0, description="1-based turn/step iteration index.")


class ThinkingEvent(BaseAgentEvent):
    """Emitted when the LLM generates reasoning or textual thought output."""

    content: str = Field(default="", description="Accumulated textual thought.")
    delta: str | None = Field(
        default=None, description="Streamed delta token fragment if streaming."
    )


class ToolStartEvent(BaseAgentEvent):
    """Emitted immediately prior to invoking a tool."""

    tool_id: str = Field(default="", description="Unique identifier for this tool call.")
    tool_name: str = Field(description="Name of the tool being executed.")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Arguments passed to the tool."
    )
    risk_level: str = Field(default="read", description="Security risk classification.")


class ToolEndEvent(BaseAgentEvent):
    """Emitted immediately after a tool finishes execution."""

    tool_id: str = Field(default="", description="Unique identifier for this tool call.")
    tool_name: str = Field(description="Name of the tool executed.")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Arguments passed to the tool."
    )
    result: ToolResult = Field(description="Execution result returned by the tool.")
    duration_ms: float = Field(default=0.0, description="Tool execution duration in milliseconds.")


class DiffEvent(BaseAgentEvent):
    """Emitted when a unified diff is generated or applied by a file tool."""

    path: str = Field(description="Workspace relative path of the modified file.")
    diff: str = Field(description="Unified diff text with additions and removals.")
    summary: str = Field(default="", description="Short human-readable diff summary.")


class FinalAnswerEvent(BaseAgentEvent):
    """Emitted when the agent produces its final text response without tool calls."""

    content: str = Field(description="Final answer text provided by the model.")
    total_steps: int = Field(default=0, description="Total execution turns completed.")


class NudgeEvent(BaseAgentEvent):
    """Emitted when loop detection identifies repeated identical tool invocations."""

    message: str = Field(description="Nudge warning message injected into the conversation.")
    repetition_count: int = Field(default=0, description="Number of times this call was repeated.")
    tool_name: str = Field(default="", description="Name of the repeated tool.")


class AgentHaltEvent(BaseAgentEvent):
    """Emitted when the agent loop is terminated due to max steps or severe loop repetition."""

    reason: str = Field(description="Explanation for why execution was terminated.")
    total_steps: int = Field(default=0, description="Total steps completed prior to halt.")


class PlanCreatedEvent(BaseAgentEvent):
    """Emitted when the planner model produces a validated execution plan."""

    plan_goal: str = Field(description="High-level goal of the plan.")
    total_steps: int = Field(default=0, description="Number of planned execution steps.")
    steps: list[dict[str, Any]] = Field(
        default_factory=list, description="Serialized plan step dictionaries."
    )
    risks: list[str] = Field(default_factory=list, description="Identified execution risks.")


class StepStartedEvent(BaseAgentEvent):
    """Emitted when execution begins for a specific plan step."""

    step_number: int = Field(description="1-based index of this step in the plan.")
    total_steps: int = Field(description="Total number of steps in the active plan.")
    title: str = Field(description="Short title of the step.")
    instructions: str = Field(default="", description="Instructions for this step.")
    files_to_read: list[str] = Field(default_factory=list, description="Target files to read.")
    files_to_change: list[str] = Field(default_factory=list, description="Target files to modify.")


class StepDoneEvent(BaseAgentEvent):
    """Emitted when a plan step completes execution."""

    step_number: int = Field(description="1-based index of the completed step.")
    total_steps: int = Field(description="Total number of steps in the plan.")
    title: str = Field(description="Short title of the completed step.")
    result_summary: str = Field(default="", description="Summary of the step outcome.")
    success: bool = Field(default=True, description="Whether the step completed successfully.")


class PlanRevisedEvent(BaseAgentEvent):
    """Emitted when the planner updates remaining steps after reviewing step execution."""

    explanation: str = Field(description="Reasoning or description of plan modifications.")
    total_steps: int = Field(description="Updated total count of steps.")
    remaining_steps: list[dict[str, Any]] = Field(
        default_factory=list, description="Updated remaining steps."
    )


# Union type representing any event emitted by the agent
AgentEvent = (
    ThinkingEvent
    | ToolStartEvent
    | ToolEndEvent
    | DiffEvent
    | FinalAnswerEvent
    | NudgeEvent
    | AgentHaltEvent
    | PlanCreatedEvent
    | StepStartedEvent
    | StepDoneEvent
    | PlanRevisedEvent
)

EventListener = Callable[[AgentEvent], None | Coroutine[Any, Any, None]]


class EventBus:
    """Decoupled event dispatcher allowing UIs and extensions to listen to agent steps."""

    def __init__(self) -> None:
        self._listeners: list[EventListener] = []

    def subscribe(self, listener: EventListener) -> None:
        """Register an event listener callback (sync or async)."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: EventListener) -> None:
        """Remove a previously registered event listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def emit(self, event: AgentEvent) -> None:
        """Dispatch an event asynchronously to all registered subscribers."""
        for listener in list(self._listeners):
            try:
                res = listener(event)
                if inspect.isawaitable(res):
                    await res
            except Exception:
                # Subscriber errors must never crash the core agent loop
                pass
