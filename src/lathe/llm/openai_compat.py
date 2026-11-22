"""OpenAI-compatible server client (llama.cpp server, LM Studio, vLLM)."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from lathe.config import RoleConfig
from lathe.llm.base import LLMClient, LLMError, ModelNotFoundError
from lathe.llm.types import Message, StreamChunk, ToolCall, ToolSpec, Usage


class OpenAICompatClient(LLMClient):
    """Generic client for any server supporting OpenAI /v1/chat/completions."""

    def __init__(
        self,
        role_config: RoleConfig,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(role_config=role_config)
        raw_base = (
            role_config.base_url
            or base_url
            or os.environ.get("OPENAI_BASE_URL", "http://localhost:8000/v1")
        ).rstrip("/")
        self.base_url = raw_base
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "EMPTY")
        self.timeout = timeout
        self.max_retries = max_retries
        self._custom_client = client

    def _get_http_client(self) -> httpx.AsyncClient:
        """Return injected client or instantiate a default async client."""
        if self._custom_client is not None:
            return self._custom_client
        return httpx.AsyncClient(timeout=self.timeout)

    def _get_endpoint(self) -> str:
        """Construct full chat completions URL."""
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def _format_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Format domain messages into OpenAI chat message dicts."""
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id or f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": (
                                json.dumps(tc.arguments)
                                if isinstance(tc.arguments, dict)
                                else tc.arguments
                            ),
                        },
                    }
                    for i, tc in enumerate(msg.tool_calls)
                ]
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            formatted.append(entry)
        return formatted

    def _build_payload(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> dict[str, Any]:
        """Construct JSON request payload."""
        payload: dict[str, Any] = {
            "model": self.role_config.model,
            "messages": self._format_messages(messages),
            "stream": stream,
            "temperature": self.role_config.temperature,
            "max_tokens": self.role_config.max_tokens,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if tools:
            payload["tools"] = [t.to_ollama_format() for t in tools]
        return payload

    async def _send_request_with_retry(
        self,
        http_client: httpx.AsyncClient,
        payload: dict[str, Any],
    ) -> httpx.Response:
        """Send chat request with exponential backoff on connection errors or timeouts."""
        endpoint = self._get_endpoint()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                req = http_client.build_request("POST", endpoint, json=payload, headers=headers)
                response = await http_client.send(req, stream=True)

                if response.status_code == 404:
                    await response.aread()
                    raise ModelNotFoundError(
                        model_name=self.role_config.model,
                        suggestion=(
                            f"Verify that '{self.role_config.model}' is loaded at {self.base_url}."
                        ),
                    )

                if response.status_code >= 400:
                    body = await response.aread()
                    body_text = body.decode("utf-8", errors="replace")
                    raise LLMError(f"Server returned HTTP {response.status_code}: {body_text}")

                return response

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    backoff = 0.5 * (2**attempt)
                    await asyncio.sleep(backoff)
                else:
                    break

        raise LLMError(
            f"Failed to connect to OpenAI server at {self.base_url} "
            f"after {self.max_retries} retries.",
            details={"original_error": str(last_error)},
        )

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        """Stream SSE chunks from OpenAI-compatible server."""
        payload = self._build_payload(messages, tools=tools, stream=stream)
        owns_client = self._custom_client is None
        http_client = self._get_http_client()

        try:
            response = await self._send_request_with_retry(http_client, payload)
            try:
                terminal_emitted = False
                last_usage: Usage | None = None

                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue

                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        if not terminal_emitted:
                            yield StreamChunk(done=True, finish_reason="stop", usage=last_usage)
                            terminal_emitted = True
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # Check for usage object
                    usage_obj = None
                    if "usage" in data and data["usage"]:
                        u = data["usage"]
                        usage_obj = Usage(
                            prompt_tokens=u.get("prompt_tokens", 0) or 0,
                            completion_tokens=u.get("completion_tokens", 0) or 0,
                            total_tokens=u.get("total_tokens", 0) or 0,
                        )
                        last_usage = usage_obj

                    choices = data.get("choices", [])
                    if not choices:
                        if usage_obj and not terminal_emitted:
                            yield StreamChunk(done=True, finish_reason="stop", usage=usage_obj)
                            terminal_emitted = True
                        continue

                    choice = choices[0]
                    delta = choice.get("delta", {})
                    content_delta = delta.get("content", "") or ""
                    finish_reason = choice.get("finish_reason")

                    raw_tool_calls = delta.get("tool_calls", [])
                    if raw_tool_calls:
                        for raw_tc in raw_tool_calls:
                            fn = raw_tc.get("function", {})
                            args = fn.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = {"raw": args}
                            tc = ToolCall(
                                id=raw_tc.get("id", ""),
                                name=fn.get("name", ""),
                                arguments=args,
                            )
                            yield StreamChunk(tool_call_delta=tc, done=False)

                    if content_delta:
                        yield StreamChunk(delta=content_delta, done=False)

                    if finish_reason:
                        yield StreamChunk(
                            done=True,
                            finish_reason=finish_reason,
                            usage=usage_obj or last_usage,
                        )
                        terminal_emitted = True
                        break
            finally:
                await response.aclose()
        finally:
            if owns_client:
                await http_client.aclose()
