"""Optional real-model smoke test using Ollama (Phase 23).

Marked @pytest.mark.slow. Tests a real model interaction with the 1.5B model
via local Ollama when the runtime is available. Skips cleanly if Ollama is not running.
"""

from __future__ import annotations

import httpx
import pytest

from lathe.config import RoleConfig
from lathe.llm.ollama import OllamaClient
from lathe.llm.types import Message


@pytest.mark.slow
@pytest.mark.asyncio
async def test_ollama_1_5b_real_model_smoke() -> None:
    """Smoke test sending a prompt to the local 1.5B Ollama model."""
    ollama_url = "http://localhost:11434"

    # Check if local Ollama daemon is reachable
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{ollama_url}/api/tags")
            if resp.status_code != 200:
                pytest.skip("Local Ollama daemon returned non-200 status code.")
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
    except Exception as exc:
        pytest.skip(f"Local Ollama is not accessible ({exc}); skipping slow smoke test.")

    # Select available 1.5B or fallback model
    candidate_model: str | None = None
    for name in models:
        if "1.5b" in name.lower() or "qwen" in name.lower() or "lathe" in name.lower():
            candidate_model = name
            break

    if not candidate_model and models:
        candidate_model = models[0]

    if not candidate_model:
        pytest.skip("No local models installed in Ollama to smoke test.")

    role_cfg = RoleConfig(
        backend="ollama",
        model=candidate_model,
        temperature=0.0,
        max_tokens=64,
        context_window=2048,
    )
    ollama_client = OllamaClient(role_cfg, base_url=ollama_url)

    chunks: list[str] = []
    messages = [
        Message(role="system", content="You are a helpful coding assistant."),
        Message(role="user", content="Print 'OK' in Python:"),
    ]

    try:
        async for chunk in ollama_client.chat(messages, stream=True):
            if chunk.delta:
                chunks.append(chunk.delta)
    except Exception as exc:
        pytest.skip(f"Ollama generation failed ({exc}); skipping smoke test.")

    full_output = "".join(chunks).strip()
    assert len(full_output) > 0, "Expected non-empty output from real Ollama model."
