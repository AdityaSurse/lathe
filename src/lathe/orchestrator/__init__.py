"""Orchestrator package coordinating multi-model planning, coding, and review."""

from typing import Protocol


class Orchestrator(Protocol):
    """Protocol for the dual-LLM agent orchestrator loop."""

    def plan(self, prompt: str) -> list[str]:
        """Formulate a step-by-step task execution plan."""
        ...

    def execute_step(self, step: str) -> str:
        """Execute an individual step via the coder and reviewer models."""
        ...
