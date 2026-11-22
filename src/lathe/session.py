"""Session lifecycle manager for Lathe interactive terminal coding sessions."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionConfig:
    """Configuration options for an active agent session."""

    workspace_dir: str = "."
    planner_model: str = "deepseek-r1:32b"
    coder_model: str = "qwen2.5-coder:7b"
    router_model: str = "qwen2.5-coder:1.5b"
    auto_approve: bool = False
    max_steps: int = 10


@dataclass
class Session:
    """Manages conversational history, state transitions, and workspace interactions."""

    config: SessionConfig = field(default_factory=SessionConfig)
    history: list[dict[str, Any]] = field(default_factory=list)
    active: bool = False

    def start(self) -> None:
        """Initialize and activate the interactive session."""
        self.active = True

    def stop(self) -> None:
        """Gracefully terminate the session."""
        self.active = False
