"""Tests for backend-agnostic LLM interface, types, Ollama driver, and factory."""

import json
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from lathe.cli import app
from lathe.config import RoleConfig
from lathe.llm.base import ModelNotFoundError
from lathe.llm.factory import get_client
from lathe.llm.ollama import OllamaClient
from lathe.llm.types import Message, StreamChunk, ToolCall, ToolSpec, Usage

runner = CliRunner()


def test_llm_types() -> None:
    """Verify core domain representations for messages, tools, and usage."""
    msg = Message(role="user", content="Hello world")
    assert msg.role == "user"
    assert msg.content == "Hello world"
    assert msg.tool_calls is None

    spec = ToolSpec(
        name="read_file",
        description="Read file contents",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    ollama_tool = spec.to_ollama_format()
    assert ollama_tool["type"] == "function"
    assert ollama_tool["function"]["name"] == "read_file"

    call = ToolCall(id="call_1", name="read_file", arguments={"path": "main.py"})
    assert call.name == "read_file"
    assert call.arguments["path"] == "main.py"

    usage = Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30, duration_ms=150.0)
    chunk = StreamChunk(delta="def foo():", usage=usage)
    assert chunk.delta == "def foo():"
    assert chunk.usage is not None
    assert chunk.usage.total_tokens == 30


@pytest.mark.asyncio
async def test_ollama_streaming_chat() -> None:
    """Verify Ollama streaming chat yields text deltas and terminal metrics."""
    stream_lines = [
        json.dumps(
            {
                "model": "qwen2.5-coder:7b",
                "message": {"role": "assistant", "content": "Hello "},
                "done": False,
            }
        )
        + "\n",
        json.dumps(
            {
                "model": "qwen2.5-coder:7b",
                "message": {"role": "assistant", "content": "world!"},
                "done": False,
            }
        )
        + "\n",
        json.dumps(
            {
                "model": "qwen2.5-coder:7b",
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "prompt_eval_count": 8,
                "eval_count": 2,
                "total_duration": 50_000_000,
            }
        )
        + "\n",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        req_data = json.loads(request.content.decode("utf-8"))
        assert req_data["model"] == "qwen2.5-coder:7b"
        assert req_data["stream"] is True
        return httpx.Response(200, content="".join(stream_lines).encode("utf-8"))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_http:
        role_cfg = RoleConfig(backend="ollama", model="qwen2.5-coder:7b")
        client = OllamaClient(role_config=role_cfg, client=mock_http)

        messages = [Message(role="user", content="Say hello")]
        chunks: list[StreamChunk] = []
        async for chunk in client.chat(messages, stream=True):
            chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0].delta == "Hello "
        assert chunks[1].delta == "world!"
        assert chunks[2].done is True
        assert chunks[2].usage is not None
        assert chunks[2].usage.completion_tokens == 2
        assert chunks[2].usage.prompt_tokens == 8


@pytest.mark.asyncio
async def test_ollama_complete_accumulation() -> None:
    """Verify complete() consolidates streamed chunks into a single Message."""
    stream_lines = [
        json.dumps(
            {
                "model": "qwen2.5-coder:7b",
                "message": {"role": "assistant", "content": "print('lathe')"},
                "done": False,
            }
        )
        + "\n",
        json.dumps(
            {
                "model": "qwen2.5-coder:7b",
                "message": {"role": "assistant", "content": ""},
                "done": True,
            }
        )
        + "\n",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="".join(stream_lines).encode("utf-8"))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_http:
        role_cfg = RoleConfig(backend="ollama", model="qwen2.5-coder:7b")
        client = OllamaClient(role_config=role_cfg, client=mock_http)

        res = await client.complete([Message(role="user", content="Write python print")])
        assert res.role == "assistant"
        assert res.content == "print('lathe')"
        assert res.tool_calls is None


@pytest.mark.asyncio
async def test_ollama_native_tool_calling() -> None:
    """Verify Ollama native tool calls are parsed and populated on the completion message."""
    stream_lines = [
        json.dumps(
            {
                "model": "qwen2.5-coder:7b",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "function": {
                                "name": "read_file",
                                "arguments": {"path": "src/lathe/cli.py"},
                            },
                        }
                    ],
                },
                "done": False,
            }
        )
        + "\n",
        json.dumps(
            {
                "model": "qwen2.5-coder:7b",
                "message": {"role": "assistant", "content": ""},
                "done": True,
            }
        )
        + "\n",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        req_data = json.loads(request.content.decode("utf-8"))
        assert "tools" in req_data
        assert req_data["tools"][0]["function"]["name"] == "read_file"
        return httpx.Response(200, content="".join(stream_lines).encode("utf-8"))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_http:
        role_cfg = RoleConfig(backend="ollama", model="qwen2.5-coder:7b")
        client = OllamaClient(role_config=role_cfg, client=mock_http)

        tools = [
            ToolSpec(
                name="read_file",
                description="Read file",
                parameters={"properties": {"path": {"type": "string"}}},
            )
        ]
        res = await client.complete(
            [Message(role="user", content="Read src/lathe/cli.py")],
            tools=tools,
        )
        assert res.tool_calls is not None
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].name == "read_file"
        assert res.tool_calls[0].arguments == {"path": "src/lathe/cli.py"}


@pytest.mark.asyncio
async def test_ollama_model_not_found_error() -> None:
    """Verify ModelNotFoundError suggests exact `ollama pull` command."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'missing-model' not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_http:
        role_cfg = RoleConfig(backend="ollama", model="missing-model")
        client = OllamaClient(role_config=role_cfg, client=mock_http)

        with pytest.raises(ModelNotFoundError) as exc_info:
            async for _ in client.chat([Message(role="user", content="hi")]):
                pass

        err = exc_info.value
        assert "missing-model" in err.model_name
        assert "ollama pull missing-model" in err.suggestion


@pytest.mark.asyncio
async def test_ollama_timeout_and_retry() -> None:
    """Verify OllamaClient automatically retries after connection or timeout errors."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("Connection refused by mock")
        # Second attempt succeeds
        line = json.dumps(
            {
                "model": "qwen2.5-coder:7b",
                "message": {"role": "assistant", "content": "Recovered!"},
                "done": True,
            }
        )
        return httpx.Response(200, content=(line + "\n").encode("utf-8"))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_http:
        role_cfg = RoleConfig(backend="ollama", model="qwen2.5-coder:7b")
        client = OllamaClient(
            role_config=role_cfg,
            client=mock_http,
            max_retries=2,
        )

        res = await client.complete([Message(role="user", content="test")])
        assert attempts == 2
        assert res.content == "Recovered!"


def test_factory_get_client() -> None:
    """Verify factory builds appropriate client classes from role strings."""
    coder_client = get_client("coder")
    assert isinstance(coder_client, OllamaClient)
    assert "Qwen2.5-Coder-7B" in coder_client.role_config.model

    router_client = get_client("router")
    assert isinstance(router_client, OllamaClient)
    assert "1.5B" in router_client.role_config.model

    with pytest.raises(ValueError, match="Unknown role 'wizard'"):
        get_client("wizard")  # type: ignore[arg-type]


def test_cli_ask_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test `lathe ask` command using a mocked stream."""

    async def mock_chat(
        self: Any,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> Any:
        yield StreamChunk(delta="Hello ")
        yield StreamChunk(delta="world!")
        yield StreamChunk(
            done=True,
            usage=Usage(
                prompt_tokens=4,
                completion_tokens=2,
                total_tokens=6,
                duration_ms=100.0,
            ),
        )

    monkeypatch.setattr(OllamaClient, "chat", mock_chat)

    res = runner.invoke(app, ["ask", "Say hello", "--role", "coder"])
    assert res.exit_code == 0
    assert "Hello world!" in res.stdout
    assert "tokens in" in res.stdout
    assert "tokens/sec" in res.stdout
