"""LLM interface package providing unified access to local and cloud backends."""

from typing import Any, Protocol


class LLMBackend(Protocol):
    """Protocol for LLM providers (Ollama, Hugging Face, OpenAI-compatible)."""

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate a completion for the provided prompt."""
        ...
