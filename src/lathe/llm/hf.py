"""Hugging Face Inference Providers API client with streaming and tool fallback."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from huggingface_hub import AsyncInferenceClient

from lathe.config import RoleConfig
from lathe.llm.base import LLMClient, LLMError, ModelNotFoundError
from lathe.llm.types import Message, StreamChunk, ToolCall, ToolSpec, Usage

FALLBACK_TOOL_SYSTEM_PROMPT = """You have access to the following tools:
{tool_specs}

To invoke a tool, you MUST respond ONLY with a JSON object inside a ```json ... ``` block:
```json
{{"name": "<tool_name>", "arguments": {{<arguments>}}}}
```
Do not write any introductory or concluding text when invoking a tool.
"""


class HFClient(LLMClient):
    """LLM client connecting to Hugging Face Inference Providers API."""

    def __init__(
        self,
        role_config: RoleConfig,
        token: str | None = None,
        provider: str | None = None,
        supports_tools: bool | None = None,
        max_retries: int = 3,
        client: Any | None = None,
    ) -> None:
        super().__init__(role_config=role_config)
        self.token = token
        self.provider = provider or role_config.provider or "auto"
        self.supports_tools = (
            supports_tools if supports_tools is not None else role_config.supports_tools
        )
        self.max_retries = max_retries
        self._custom_client = client

    def _get_client(self) -> AsyncInferenceClient:
        """Return the injected test client or instantiate a fresh AsyncInferenceClient."""
        if self._custom_client is not None:
            return self._custom_client  # type: ignore[no-any-return]
        return AsyncInferenceClient(
            model=self.role_config.model,
            provider=self.provider,  # type: ignore[arg-type]
            token=self.token,
        )

    def _format_messages(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        fallback_tools: bool = False,
    ) -> list[dict[str, Any]]:
        """Format domain messages into Hugging Face chat completion messages."""
        formatted: list[dict[str, Any]] = []

        # If model doesn't support native tools, inject schema into system prompt
        if fallback_tools and tools:
            specs_text = json.dumps([t.model_dump() for t in tools], indent=2)
            sys_prompt = FALLBACK_TOOL_SYSTEM_PROMPT.format(tool_specs=specs_text)
            formatted.append({"role": "system", "content": sys_prompt})

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

    def _extract_fallback_tool_call(self, text: str) -> ToolCall | None:
        """Parse JSON tool call block from text response."""
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        raw_json = json_match.group(1) if json_match else text.strip()
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                # Handle {"tool_call": {...}} or {"name": ..., "arguments": ...}
                if "tool_call" in parsed and isinstance(parsed["tool_call"], dict):
                    parsed = parsed["tool_call"]
                if "name" in parsed:
                    return ToolCall(
                        name=parsed["name"],
                        arguments=parsed.get("arguments", {}),
                    )
        except Exception:
            pass
        return None

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        """Stream responses from Hugging Face Inference Providers API."""
        client = self._get_client()
        fallback_mode = not self.supports_tools and bool(tools)

        hf_tools = (
            [t.to_ollama_format() for t in tools] if (tools and self.supports_tools) else None
        )

        formatted_messages = self._format_messages(
            messages,
            tools=tools,
            fallback_tools=fallback_mode,
        )

        stream_obj = None
        for attempt in range(self.max_retries + 1):
            try:
                stream_obj = await client.chat_completion(
                    messages=formatted_messages,
                    model=self.role_config.model,
                    stream=True,
                    temperature=self.role_config.temperature,
                    max_tokens=self.role_config.max_tokens,
                    tools=hf_tools,  # type: ignore[arg-type]
                )
                break
            except Exception as exc:
                err_str = str(exc).lower()
                status_code = getattr(getattr(exc, "response", None), "status_code", None)

                # HF router quota / payment / credit exhaustion handling
                if (
                    status_code == 402
                    or "402" in err_str
                    or "payment required" in err_str
                    or "credits" in err_str
                ):
                    raise LLMError(
                        "HF free quota hit — switch planner to ollama in lathe.toml"
                    ) from exc

                # 429 Quota handling with exponential backoff
                if (
                    status_code == 429
                    or "429" in err_str
                    or "quota" in err_str
                    or "rate limit" in err_str
                    or "too many requests" in err_str
                ):
                    if attempt < self.max_retries:
                        backoff = 0.5 * (2**attempt)
                        await asyncio.sleep(backoff)
                        continue
                    raise LLMError(
                        "HF free quota hit — switch planner to ollama in lathe.toml"
                    ) from exc

                # Check if model lacks native tool calling support
                if hf_tools and (
                    "tool" in err_str
                    or "function" in err_str
                    or "not support" in err_str
                    or "unsupported" in err_str
                ):
                    self.supports_tools = False
                    # Retry once with fallback text-based tool protocol
                    return
                if "not found" in err_str or status_code == 404:
                    raise ModelNotFoundError(
                        model_name=self.role_config.model,
                        suggestion="Verify the Hugging Face model repository ID.",
                    ) from exc

                raise LLMError(f"Hugging Face Inference API error: {exc}") from exc

        if stream_obj is None:
            # If native tools failed, run fallback text tools
            if not self.supports_tools and tools:
                async for chunk in self.chat(messages, tools=tools, stream=stream):
                    yield chunk
            return

        accumulated_text = ""
        terminal_emitted = False

        try:
            async for hf_chunk in stream_obj:  # type: ignore[union-attr]
                if not hf_chunk.choices:
                    # Check for usage-only final chunk
                    if getattr(hf_chunk, "usage", None):
                        u = hf_chunk.usage
                        usage_obj = Usage(
                            prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
                            completion_tokens=getattr(u, "completion_tokens", 0) or 0,
                            total_tokens=getattr(u, "total_tokens", 0) or 0,
                        )
                        yield StreamChunk(done=True, finish_reason="stop", usage=usage_obj)
                        terminal_emitted = True
                    continue

                choice = hf_chunk.choices[0]
                delta = choice.delta
                text_delta = getattr(delta, "content", "") or ""
                finish_reason = getattr(choice, "finish_reason", None)

                # Native tool call deltas
                raw_tool_calls = getattr(delta, "tool_calls", None)
                if raw_tool_calls:
                    for raw_tc in raw_tool_calls:
                        fn = (
                            raw_tc.get("function")
                            if isinstance(raw_tc, dict)
                            else getattr(raw_tc, "function", None)
                        )
                        fn_name = (
                            fn.get("name", "")
                            if isinstance(fn, dict)
                            else (getattr(fn, "name", "") or "")
                        )
                        fn_args = (
                            fn.get("arguments", {})
                            if isinstance(fn, dict)
                            else (getattr(fn, "arguments", {}) or {})
                        )
                        tc_id = (
                            raw_tc.get("id", "")
                            if isinstance(raw_tc, dict)
                            else (getattr(raw_tc, "id", "") or "call_0")
                        )
                        if isinstance(fn_args, str):
                            try:
                                fn_args = json.loads(fn_args)
                            except Exception:
                                fn_args = {"raw": fn_args}
                        tc = ToolCall(
                            id=tc_id,
                            name=fn_name,
                            arguments=fn_args,
                        )
                        yield StreamChunk(tool_call_delta=tc, done=False)

                if text_delta:
                    accumulated_text += text_delta
                    yield StreamChunk(delta=text_delta, done=False)

                # Check usage on chunk if provided
                usage_data = getattr(hf_chunk, "usage", None)
                chunk_usage: Usage | None = None
                if usage_data:
                    chunk_usage = Usage(
                        prompt_tokens=getattr(usage_data, "prompt_tokens", 0) or 0,
                        completion_tokens=getattr(usage_data, "completion_tokens", 0) or 0,
                        total_tokens=getattr(usage_data, "total_tokens", 0) or 0,
                    )

                if finish_reason:
                    # If in fallback mode, inspect accumulated text for tool calls
                    if fallback_mode:
                        fallback_tc = self._extract_fallback_tool_call(accumulated_text)
                        if fallback_tc:
                            yield StreamChunk(tool_call_delta=fallback_tc, done=False)

                    yield StreamChunk(
                        done=True,
                        finish_reason=finish_reason,
                        usage=chunk_usage,
                    )
                    terminal_emitted = True
                    break

            if not terminal_emitted:
                yield StreamChunk(done=True, finish_reason="stop")
        finally:
            pass
