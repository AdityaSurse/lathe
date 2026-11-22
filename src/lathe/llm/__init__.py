"""LLM provider abstraction layer and unified client interfaces."""

from lathe.llm.base import LLMClient, LLMError, ModelNotFoundError
from lathe.llm.factory import get_client
from lathe.llm.ollama import OllamaClient
from lathe.llm.types import Message, RoleType, StreamChunk, ToolCall, ToolSpec, Usage

__all__ = [
    "LLMClient",
    "LLMError",
    "Message",
    "ModelNotFoundError",
    "OllamaClient",
    "RoleType",
    "StreamChunk",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "get_client",
]
