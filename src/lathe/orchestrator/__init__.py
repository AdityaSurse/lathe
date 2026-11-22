"""Orchestrator package coordinating multi-model planning, coding, review, and agent execution."""

from lathe.orchestrator.agent import Agent, run_one_shot
from lathe.orchestrator.dual import DualAgent, Plan, PlanRevision, PlanStep, run_dual_one_shot
from lathe.orchestrator.events import (
    AgentEvent,
    AgentHaltEvent,
    DiffEvent,
    EventBus,
    FinalAnswerEvent,
    NudgeEvent,
    PlanCreatedEvent,
    PlanRevisedEvent,
    StepDoneEvent,
    StepStartedEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
)

__all__ = [
    "Agent",
    "AgentEvent",
    "AgentHaltEvent",
    "DiffEvent",
    "DualAgent",
    "EventBus",
    "FinalAnswerEvent",
    "NudgeEvent",
    "Plan",
    "PlanCreatedEvent",
    "PlanRevision",
    "PlanRevisedEvent",
    "PlanStep",
    "StepDoneEvent",
    "StepStartedEvent",
    "ThinkingEvent",
    "ToolEndEvent",
    "ToolStartEvent",
    "run_dual_one_shot",
    "run_one_shot",
]
