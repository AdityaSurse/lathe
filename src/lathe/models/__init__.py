"""Model management package for searching, pulling, probing, and assigning LLMs."""

from lathe.models.capabilities import (
    CapabilityProtocol,
    get_capabilities_file_path,
    get_capability,
    load_capabilities,
    save_capability,
)
from lathe.models.cli import models_app
from lathe.models.local import get_local_ollama_models
from lathe.models.presets import (
    PRESETS,
    ModelPreset,
    apply_preset_to_toml_file,
    format_messages_with_system_fallback,
    generate_preset_toml,
    get_preset,
    list_presets,
    strip_thinking_blocks,
)
from lathe.models.probe import probe_model
from lathe.models.pull import (
    normalize_ollama_model_name,
    pull_model_stream,
    pull_model_with_progress,
)
from lathe.models.ram import format_bytes, get_available_ram_bytes
from lathe.models.search import GGUFRepoResult, search_gguf_repos

__all__ = [
    "CapabilityProtocol",
    "GGUFRepoResult",
    "ModelPreset",
    "PRESETS",
    "apply_preset_to_toml_file",
    "format_bytes",
    "format_messages_with_system_fallback",
    "generate_preset_toml",
    "get_available_ram_bytes",
    "get_capabilities_file_path",
    "get_capability",
    "get_local_ollama_models",
    "get_preset",
    "list_presets",
    "load_capabilities",
    "models_app",
    "normalize_ollama_model_name",
    "probe_model",
    "pull_model_stream",
    "pull_model_with_progress",
    "save_capability",
    "search_gguf_repos",
    "strip_thinking_blocks",
]
