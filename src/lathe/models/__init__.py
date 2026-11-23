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
    "format_bytes",
    "get_available_ram_bytes",
    "get_capabilities_file_path",
    "get_capability",
    "get_local_ollama_models",
    "load_capabilities",
    "models_app",
    "normalize_ollama_model_name",
    "probe_model",
    "pull_model_stream",
    "pull_model_with_progress",
    "save_capability",
    "search_gguf_repos",
]
