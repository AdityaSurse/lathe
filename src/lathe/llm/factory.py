"""Factory module resolving and constructing LLM client backends from configuration."""

import os
from typing import Any, Literal

import httpx

from lathe.config import LatheConfig, RoleConfig, get_hf_token, load_config
from lathe.llm.base import LLMClient
from lathe.llm.hf import HFClient
from lathe.llm.ollama import OllamaClient
from lathe.llm.openai_compat import OpenAICompatClient
from lathe.models.capabilities import get_capability

RoleName = Literal["planner", "coder", "reviewer", "router"]


def get_client(
    role: str | RoleConfig,
    config: LatheConfig | None = None,
    client: Any | None = None,
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

    # Check cached capabilities to automatically select tool protocol
    capability = get_capability(role_config.model)
    if capability:
        proto = capability.get("tool_protocol")
        if proto == "native":
            role_config.supports_tools = True
        elif proto in ("json_fallback", "none"):
            role_config.supports_tools = False

    if role_config.backend == "ollama":
        base_url = role_config.base_url or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return OllamaClient(
            role_config=role_config,
            base_url=base_url,
            client=client if isinstance(client, httpx.AsyncClient) else None,
        )

    if role_config.backend == "hf":
        token = get_hf_token()
        return HFClient(
            role_config=role_config,
            token=token,
            provider=role_config.provider,
            supports_tools=role_config.supports_tools,
            client=client,
        )

    if role_config.backend == "openai_compat":
        return OpenAICompatClient(
            role_config=role_config,
            base_url=role_config.base_url,
            client=client if isinstance(client, httpx.AsyncClient) else None,
        )

    raise ValueError(f"Unsupported backend '{role_config.backend}'.")


get_client_for_config = get_client
