"""Context management: token counting, AST indexing, repomap, budget, and compaction."""

from typing import Any

from lathe.context.budget import (
    BudgetAllocator,
    BudgetShares,
    BudgetUsage,
    TokenCounter,
    compact_context,
    is_protected_message,
)

__all__ = [
    "BaseEmbedder",
    "BudgetAllocator",
    "BudgetShares",
    "BudgetUsage",
    "CodeChunk",
    "CodeIndex",
    "DeterministicEmbedder",
    "FileSymbols",
    "HFEmbedder",
    "OllamaEmbedder",
    "RepoMap",
    "SearchResult",
    "SentenceTransformersEmbedder",
    "SymbolDef",
    "TokenCounter",
    "chunk_file",
    "compact_context",
    "create_embedder",
    "is_protected_message",
]


def __getattr__(name: str) -> Any:
    if name in (
        "BaseEmbedder",
        "CodeChunk",
        "CodeIndex",
        "DeterministicEmbedder",
        "HFEmbedder",
        "OllamaEmbedder",
        "SearchResult",
        "SentenceTransformersEmbedder",
        "chunk_file",
        "create_embedder",
    ):
        import lathe.context.index as _idx

        return getattr(_idx, name)
    if name in ("FileSymbols", "RepoMap", "SymbolDef"):
        import lathe.context.repomap as _rm

        return getattr(_rm, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
