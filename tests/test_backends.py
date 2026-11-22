"""Contract and integration tests for all LLM backends: Ollama, Hugging Face, and OpenAI-compat."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from lathe.config import RoleConfig
from lathe.llm.base import LLMClient, LLMError
from lathe.llm.hf import HFClient
from lathe.llm.ollama import OllamaClient
from lathe.llm.openai_compat import OpenAICompatClient
from lathe.llm.types import Message, ToolSpec


# --- Mock helpers for HF AsyncInferenceClient ---
@dataclass
class MockDelta:
    content: str | None = None
    tool_calls: list[Any] | None = None


@dataclass
class MockChoice:
    delta: MockDelta
    finish_reason: str | None = None


@dataclass
class MockUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 5
    total_tokens: int = 15


@dataclass
class MockHFStreamChunk:
    choices: list[MockChoice]
    usage: MockUsage | None = None


class MockAsyncInferenceClient:
    """Mock Hugging Face AsyncInferenceClient returning controlled stream responses."""

    def __init__(
        self,
        responses: list[MockHFStreamChunk] | None = None,
        should_fail_429: bool = False,
        should_fail_402: bool = False,
    ) -> None:
        self.responses = responses or []
        self.should_fail_429 = should_fail_429
        self.should_fail_402 = should_fail_402
        self.attempt_count = 0

    async def chat_completion(self, *args: Any, **kwargs: Any) -> AsyncIterator[MockHFStreamChunk]:
        self.attempt_count += 1
        if self.should_fail_429:
            response = httpx.Response(
                429,
                json={"error": "Rate limit exceeded: free quota reached"},
            )
            req = httpx.Request("POST", "https://api.hf.co")
            raise httpx.HTTPStatusError("429 Too Many Requests", request=req, response=response)

        if self.should_fail_402:
            response = httpx.Response(
                402,
                json={"error": "Payment required: purchase pre-paid credits"},
            )
            req = httpx.Request("POST", "https://api.hf.co")
            raise httpx.HTTPStatusError("402 Payment Required", request=req, response=response)

        async def _generator() -> AsyncIterator[MockHFStreamChunk]:
            for r in self.responses:
                yield r

        return _generator()


def create_mock_ollama_client(tool_call: bool = False) -> OllamaClient:
    """Create OllamaClient with mock httpx transport."""
    if tool_call:
        tc = [{"id": "c1", "function": {"name": "test_tool", "arguments": {"x": 1}}}]
        lines = [
            json.dumps(
                {"model": "m", "message": {"role": "assistant", "tool_calls": tc}, "done": False}
            )
            + "\n",
            json.dumps(
                {
                    "model": "m",
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "prompt_eval_count": 5,
                    "eval_count": 2,
                }
            )
            + "\n",
        ]
    else:
        lines = [
            json.dumps(
                {"model": "m", "message": {"role": "assistant", "content": "Hello "}, "done": False}
            )
            + "\n",
            json.dumps(
                {"model": "m", "message": {"role": "assistant", "content": "world!"}, "done": False}
            )
            + "\n",
            json.dumps(
                {
                    "model": "m",
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "prompt_eval_count": 5,
                    "eval_count": 2,
                }
            )
            + "\n",
        ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="".join(lines).encode("utf-8"))

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    cfg = RoleConfig(backend="ollama", model="test-coder")
    return OllamaClient(role_config=cfg, client=http_client)


def create_mock_hf_client(tool_call: bool = False) -> HFClient:
    """Create HFClient with mock AsyncInferenceClient."""
    if tool_call:
        tc = [{"id": "c1", "function": {"name": "test_tool", "arguments": {"x": 1}}}]
        chunks = [
            MockHFStreamChunk(
                choices=[
                    MockChoice(
                        delta=MockDelta(content="", tool_calls=tc),
                        finish_reason=None,
                    )
                ]
            ),
            MockHFStreamChunk(
                choices=[MockChoice(delta=MockDelta(content=""), finish_reason="tool_calls")],
                usage=MockUsage(prompt_tokens=5, completion_tokens=2, total_tokens=7),
            ),
        ]
    else:
        chunks = [
            MockHFStreamChunk(
                choices=[MockChoice(delta=MockDelta(content="Hello "), finish_reason=None)]
            ),
            MockHFStreamChunk(
                choices=[MockChoice(delta=MockDelta(content="world!"), finish_reason=None)]
            ),
            MockHFStreamChunk(
                choices=[MockChoice(delta=MockDelta(content=""), finish_reason="stop")],
                usage=MockUsage(prompt_tokens=5, completion_tokens=2, total_tokens=7),
            ),
        ]

    mock_client = MockAsyncInferenceClient(responses=chunks)
    cfg = RoleConfig(backend="hf", model="deepseek-ai/DeepSeek-R1")
    return HFClient(role_config=cfg, token="hf_test", client=mock_client)


def create_mock_openai_client(tool_call: bool = False) -> OpenAICompatClient:
    """Create OpenAICompatClient with mock httpx transport."""
    if tool_call:
        tc = [{"id": "c1", "function": {"name": "test_tool", "arguments": json.dumps({"x": 1})}}]
        lines = [
            "data: "
            + json.dumps({"choices": [{"delta": {"tool_calls": tc}, "finish_reason": None}]})
            + "\n\n",
            "data: "
            + json.dumps(
                {
                    "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                }
            )
            + "\n\n",
            "data: [DONE]\n\n",
        ]
    else:
        lines = [
            "data: "
            + json.dumps({"choices": [{"delta": {"content": "Hello "}, "finish_reason": None}]})
            + "\n\n",
            "data: "
            + json.dumps({"choices": [{"delta": {"content": "world!"}, "finish_reason": None}]})
            + "\n\n",
            "data: "
            + json.dumps(
                {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                }
            )
            + "\n\n",
            "data: [DONE]\n\n",
        ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, content="".join(lines).encode("utf-8"))

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    cfg = RoleConfig(
        backend="openai_compat",
        model="vllm-model",
        base_url="http://localhost:8000/v1",
    )
    return OpenAICompatClient(role_config=cfg, client=http_client)


# --- Standard Contract Tests Across All 3 Backends ---

CLIENT_FACTORIES = [
    create_mock_ollama_client,
    create_mock_hf_client,
    create_mock_openai_client,
]


@pytest.mark.parametrize("client_factory", CLIENT_FACTORIES)
@pytest.mark.asyncio
async def test_contract_chat_streaming(client_factory: Any) -> None:
    """All three backends must stream chunks adhering to the StreamChunk contract."""
    client: LLMClient = client_factory(tool_call=False)
    chunks = [c async for c in client.chat([Message(role="user", content="Ping")])]

    # Must yield streaming text deltas
    text_deltas = [c.delta for c in chunks if c.delta]
    assert "".join(text_deltas) == "Hello world!"

    # Terminal chunk must report done=True and valid Usage
    terminal_chunks = [c for c in chunks if c.done]
    assert len(terminal_chunks) >= 1
    assert terminal_chunks[-1].done is True
    assert terminal_chunks[-1].usage is not None
    assert terminal_chunks[-1].usage.completion_tokens == 2
    assert terminal_chunks[-1].usage.prompt_tokens == 5


@pytest.mark.parametrize("client_factory", CLIENT_FACTORIES)
@pytest.mark.asyncio
async def test_contract_complete_consolidation(client_factory: Any) -> None:
    """All three backends must consolidate streaming responses into an assistant Message."""
    client: LLMClient = client_factory(tool_call=False)
    message = await client.complete([Message(role="user", content="Ping")])
    assert message.role == "assistant"
    assert message.content == "Hello world!"
    assert message.tool_calls is None


@pytest.mark.parametrize("client_factory", CLIENT_FACTORIES)
@pytest.mark.asyncio
async def test_contract_tool_calling(client_factory: Any) -> None:
    """All three backends must normalize tool calls to ToolCall instances."""
    client: LLMClient = client_factory(tool_call=True)
    spec = ToolSpec(
        name="test_tool",
        description="Test",
        parameters={"properties": {"x": {"type": "integer"}}},
    )

    message = await client.complete([Message(role="user", content="Run tool")], tools=[spec])
    assert message.tool_calls is not None
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].name == "test_tool"
    assert message.tool_calls[0].arguments == {"x": 1}


# --- Backend-Specific Tests ---


@pytest.mark.asyncio
async def test_hf_quota_error_message() -> None:
    """HFClient must raise clear message suggesting switch to ollama on 429 quota exhaustion."""
    mock_client = MockAsyncInferenceClient(should_fail_429=True)
    cfg = RoleConfig(backend="hf", model="deepseek-ai/DeepSeek-R1")
    client = HFClient(role_config=cfg, token="hf_test", client=mock_client, max_retries=1)

    with pytest.raises(LLMError) as exc_info:
        await client.complete([Message(role="user", content="hi")])

    assert "HF free quota hit — switch planner to ollama in lathe.toml" in str(exc_info.value)


@pytest.mark.asyncio
async def test_hf_402_payment_required_error_message() -> None:
    """HFClient must raise clear message suggesting switch to ollama on 402 payment required."""
    mock_client = MockAsyncInferenceClient(should_fail_402=True)
    cfg = RoleConfig(backend="hf", model="deepseek-ai/DeepSeek-R1")
    client = HFClient(role_config=cfg, token="hf_test", client=mock_client)

    with pytest.raises(LLMError) as exc_info:
        await client.complete([Message(role="user", content="hi")])

    assert "HF free quota hit — switch planner to ollama in lathe.toml" in str(exc_info.value)


@pytest.mark.asyncio
async def test_hf_fallback_tool_protocol() -> None:
    """When supports_tools=False, HFClient must parse JSON-in-text tool format."""
    fallback_response = '```json\n{"name": "fetch_code", "arguments": {"file": "main.py"}}\n```'
    chunks = [
        MockHFStreamChunk(
            choices=[MockChoice(delta=MockDelta(content=fallback_response), finish_reason=None)]
        ),
        MockHFStreamChunk(choices=[MockChoice(delta=MockDelta(content=""), finish_reason="stop")]),
    ]
    mock_client = MockAsyncInferenceClient(responses=chunks)
    cfg = RoleConfig(backend="hf", model="deepseek-ai/DeepSeek-R1", supports_tools=False)
    client = HFClient(role_config=cfg, token="hf_test", client=mock_client, supports_tools=False)

    spec = ToolSpec(
        name="fetch_code",
        description="Fetch code",
        parameters={"properties": {"file": {"type": "string"}}},
    )
    message = await client.complete([Message(role="user", content="fetch")], tools=[spec])

    assert message.tool_calls is not None
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].name == "fetch_code"
    assert message.tool_calls[0].arguments == {"file": "main.py"}
