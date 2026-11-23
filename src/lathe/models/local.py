"""Query local Ollama instance for pulled models and cross-reference with role assignments."""

from typing import Any

import httpx

from lathe.config import LatheConfig, load_config
from lathe.models.ram import format_bytes


def _models_match(model_a: str, model_b: str) -> bool:
    """Check if two model identifiers refer to the same model."""
    a = model_a.strip().lower()
    b = model_b.strip().lower()
    if a == b:
        return True
    if a.startswith("hf.co/") and a[6:] == b:
        return True
    return bool(b.startswith("hf.co/") and b[6:] == a)


async def get_local_ollama_models(
    base_url: str = "http://localhost:11434",
    client: httpx.AsyncClient | None = None,
    config: LatheConfig | None = None,
) -> list[dict[str, Any]]:
    """Fetch installed Ollama models and correlate with configured roles."""
    cfg = config or load_config(require_secrets=False)
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=10.0)

    try:
        url = f"{base_url.rstrip('/')}/api/tags"
        resp = await http_client.get(url)
        if resp.status_code != 200:
            return []

        data = resp.json()
        models = data.get("models", [])
        results: list[dict[str, Any]] = []

        for m in models:
            name = m.get("name", "")
            size = m.get("size", 0)
            modified = m.get("modified_at", "")
            roles: list[str] = []

            for r_name, r_cfg in [
                ("planner", cfg.roles.planner),
                ("coder", cfg.roles.coder),
                ("router", cfg.roles.router),
            ]:
                if _models_match(name, r_cfg.model):
                    roles.append(r_name)

            if (
                cfg.roles.reviewer
                and _models_match(name, cfg.roles.reviewer.model)
                and "planner" not in roles
            ):
                roles.append("reviewer")

            results.append(
                {
                    "name": name,
                    "size": size,
                    "size_formatted": format_bytes(size),
                    "modified_at": modified,
                    "roles": roles,
                }
            )

        return results
    finally:
        if owns_client:
            await http_client.aclose()
