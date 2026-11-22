"""Factory module resolving and constructing LLM client backends from configuration."""

import os
from typing import Literal

import httpx

from lathe.config import LatheConfig, RoleConfig, load_config
from lathe.llm.base import LLMClient
from lathe.llm.ollama import OllamaClient

RoleName = Literal["planner", "coder", "reviewer", "router"]


def get_client(
    role: str | RoleConfig,
    config: LatheConfig | None = None,
    client: httpx.AsyncClient | None = None,
) -> LLMClient:
    """Build and return the appropriate LLMClient based on role configuration.

    Args:
        role: Name of the role ("planner", "coder", "reviewer", "router") or RoleConfig instance.
        config: Optional LatheConfig to read roles from. If None, loads active configuration.
        client: Optional httpx.AsyncClient override (used primarily for test mocking).

    Returns:
        Configured LLMClient instance.
    """
    if isinstance(role, str):
        cfg = config or load_config(require_secrets=False)
        role_lower = role.lower()
        if role_lower == "planner":
            role_config = cfg.roles.planner
        elif role_lower == "coder":
            role_config = cfg.roles.coder
        elif role_lower == "router":
            role_config = cfg.roles.router
        elif role_lower == "reviewer":
            role_config = cfg.get_reviewer()
        else:
            raise ValueError(
                f"Unknown role '{role}'. Must be one of: 'planner', 'coder', 'reviewer', 'router'."
            )
    else:
        role_config = role

    if role_config.backend == "ollama":
        base_url = role_config.base_url or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return OllamaClient(role_config=role_config, base_url=base_url, client=client)

    if role_config.backend == "hf":
        raise NotImplementedError(
            "Hugging Face Inference API provider client will be integrated in Phase 5."
        )

    if role_config.backend == "openai_compat":
        raise NotImplementedError("OpenAI-compatible backend is not yet supported.")

    raise ValueError(f"Unsupported backend '{role_config.backend}'.")
