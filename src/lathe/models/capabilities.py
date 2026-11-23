"""Management of model capabilities caching in ~/.config/lathe/capabilities.json."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from lathe.config import get_global_config_path

CapabilityProtocol = Literal["native", "json_fallback", "none"]


def get_capabilities_file_path() -> Path:
    """Return path to capabilities cache file."""
    return get_global_config_path().parent / "capabilities.json"


def load_capabilities(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load cached model capabilities from disk."""
    try:
        cap_path = path or get_capabilities_file_path()
        if not cap_path.exists():
            return {}
        data = json.loads(cap_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, Exception):
        pass
    return {}


def save_capability(
    model: str,
    protocol: CapabilityProtocol,
    path: Path | None = None,
) -> None:
    """Save model capability record to cache file."""
    try:
        cap_path = path or get_capabilities_file_path()
        cap_path.parent.mkdir(parents=True, exist_ok=True)
        capabilities = load_capabilities(cap_path)

        capabilities[model] = {
            "tool_protocol": protocol,
            "supports_tools": protocol == "native",
            "probed_at": datetime.now(UTC).isoformat(),
        }
        cap_path.write_text(json.dumps(capabilities, indent=2), encoding="utf-8")
    except (OSError, Exception):
        pass


def get_capability(model: str, path: Path | None = None) -> dict[str, Any] | None:
    """Look up cached capability for a model name."""
    capabilities = load_capabilities(path)
    if model in capabilities:
        return capabilities[model]
    if model.startswith("hf.co/"):
        stripped = model[6:]
        if stripped in capabilities:
            return capabilities[stripped]
    else:
        prefixed = f"hf.co/{model}"
        if prefixed in capabilities:
            return capabilities[prefixed]
    return None
