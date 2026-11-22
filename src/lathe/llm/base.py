"""Abstract base class and error definitions for LLM provider clients."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from lathe.config import RoleConfig
from lathe.llm.types import Message, StreamChunk, ToolCall, ToolSpec


class LLMError(Exception):
    """Base exception for errors during LLM communication."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ModelNotFoundError(LLMError):
    """Raised when a requested model is not downloaded or available on the backend."""

    def __init__(self, model_name: str, suggestion: str) -> None:
        super().__init__(
            f"Model '{model_name}' is not available locally or on backend. {suggestion}"
        )
        self.model_name = model_name
        self.suggestion = suggestion


class LLMClient(ABC):
    """Abstract interface defining chat and completion for any LLM backend."""

    def __init__(self, role_config: RoleConfig) -> None:
        self.role_config = role_config

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        """Stream chunks from the LLM backend given a conversation and optional tools."""
        ...

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
    ) -> Message:
        """Accumulate streaming chunks into a single consolidated assistant message."""
        content_parts: list[str] = []
        collected_tool_calls: list[ToolCall] = []

        async for chunk in self.chat(messages, tools=tools, stream=True):
            if chunk.delta:
                content_parts.append(chunk.delta)
            if chunk.tool_call_delta:
                collected_tool_calls.append(chunk.tool_call_delta)

        full_content = "".join(content_parts)
        return Message(
            role="assistant",
            content=full_content,
            tool_calls=collected_tool_calls if collected_tool_calls else None,
        )
