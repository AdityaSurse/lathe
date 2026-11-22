"""Ollama local inference driver with streaming, tool calling, and retry logic."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from lathe.config import RoleConfig
from lathe.llm.base import LLMClient, LLMError, ModelNotFoundError
from lathe.llm.types import Message, StreamChunk, ToolCall, ToolSpec, Usage


class OllamaClient(LLMClient):
    """LLM client for local Ollama runtimes using /api/chat."""

    def __init__(
        self,
        role_config: RoleConfig,
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
        keep_alive: str = "5m",
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(role_config=role_config)
        self.base_url = (role_config.base_url or base_url).rstrip("/")
        self.timeout = timeout
        self.keep_alive = keep_alive
        self.max_retries = max_retries
        self._custom_client = client

    def _get_http_client(self) -> httpx.AsyncClient:
        """Return the provided test client or create a fresh default async client."""
        if self._custom_client is not None:
            return self._custom_client
        return httpx.AsyncClient(timeout=self.timeout)

    def _format_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Serialize domain messages into Ollama chat wire format."""
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        }
                    }
                    for tc in msg.tool_calls
                ]
            formatted.append(entry)
        return formatted

    def _build_payload(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> dict[str, Any]:
        """Construct JSON request payload according to Ollama /api/chat specs."""
        payload: dict[str, Any] = {
            "model": self.role_config.model,
            "messages": self._format_messages(messages),
            "stream": stream,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.role_config.temperature,
                "num_predict": self.role_config.max_tokens,
                "num_ctx": self.role_config.context_window,
            },
        }
        if tools:
            payload["tools"] = [t.to_ollama_format() for t in tools]
        return payload

    async def _send_request_with_retry(
        self,
        http_client: httpx.AsyncClient,
        payload: dict[str, Any],
    ) -> httpx.Response:
        """Send chat request with up to max_retries on connection drops or timeouts."""
        endpoint = f"{self.base_url}/api/chat"
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                # We initiate streaming response
                req = http_client.build_request("POST", endpoint, json=payload)
                response = await http_client.send(req, stream=True)

                if response.status_code == 404:
                    await response.aread()
                    raise ModelNotFoundError(
                        model_name=self.role_config.model,
                        suggestion=f"Pull it locally using: `ollama pull {self.role_config.model}`",
                    )

                if response.status_code >= 400:
                    body = await response.aread()
                    body_text = body.decode("utf-8", errors="replace")
                    if "model" in body_text and "not found" in body_text.lower():
                        raise ModelNotFoundError(
                            model_name=self.role_config.model,
                            suggestion=f"Pull it using: `ollama pull {self.role_config.model}`",
                        )
                    raise LLMError(
                        f"Ollama returned HTTP error {response.status_code}: {body_text}"
                    )

                return response

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    backoff = 0.5 * (2**attempt)
                    await asyncio.sleep(backoff)
                else:
                    break

        raise LLMError(
            f"Failed to connect to Ollama at {self.base_url} after {self.max_retries} retries. "
            "Ensure the Ollama service is running (`ollama serve`).",
            details={"original_error": str(last_error)},
        )

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        """Stream responses and tool calls from Ollama /api/chat."""
        payload = self._build_payload(messages, tools=tools, stream=stream)
        owns_client = self._custom_client is None
        http_client = self._get_http_client()

        try:
            response = await self._send_request_with_retry(http_client, payload)
            try:
                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg_data = data.get("message", {})
                    content_delta = msg_data.get("content", "")
                    done = data.get("done", False)

                    # Extract tool calls if present
                    raw_tool_calls = msg_data.get("tool_calls", [])
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
                            yield StreamChunk(
                                delta=content_delta,
                                tool_call_delta=tc,
                                done=False,
                            )
                            content_delta = ""

                    # Emit text delta if content present
                    if content_delta:
                        yield StreamChunk(delta=content_delta, done=False)

                    # Process terminal chunk with metrics
                    if done:
                        prompt_eval = data.get("prompt_eval_count", 0)
                        eval_count = data.get("eval_count", 0)
                        total_duration_ns = data.get("total_duration", 0)
                        duration_ms = total_duration_ns / 1_000_000.0

                        usage = Usage(
                            prompt_tokens=prompt_eval,
                            completion_tokens=eval_count,
                            total_tokens=prompt_eval + eval_count,
                            duration_ms=duration_ms,
                        )
                        yield StreamChunk(
                            delta="",
                            done=True,
                            finish_reason="stop",
                            usage=usage,
                        )
            finally:
                await response.aclose()
        finally:
            if owns_client:
                await http_client.aclose()
