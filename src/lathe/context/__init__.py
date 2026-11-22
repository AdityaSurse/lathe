"""Context management: token counting, AST indexing, repomap, budget, and compaction."""

from lathe.context.budget import (
    BudgetAllocator,
    BudgetShares,
    BudgetUsage,
    TokenCounter,
    compact_context,
    is_protected_message,
)
from lathe.context.index import (
    BaseEmbedder,
    CodeChunk,
    CodeIndex,
    DeterministicEmbedder,
    HFEmbedder,
    OllamaEmbedder,
    SearchResult,
    SentenceTransformersEmbedder,
    chunk_file,
    create_embedder,
)
from lathe.context.repomap import FileSymbols, RepoMap, SymbolDef

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
