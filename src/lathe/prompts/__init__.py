"""Prompt templates and system guidelines for Lathe agents."""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def get_agent_system_prompt() -> str:
    """Load the standard system prompt for Lathe autonomous agent loop."""
    prompt_file = _PROMPTS_DIR / "agent.md"
    if prompt_file.is_file():
        return prompt_file.read_text(encoding="utf-8")

    # Fallback if packaged without separate prompt file
    return (
        "You are Lathe, an autonomous terminal AI coding agent. "
        "Read files before editing, make the smallest targeted change, "
        "run tests after changes, never guess file contents, and explain briefly then act."
    )
