"""Memory system managing active workspace scratchpads, AST caches, and conversation compaction."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionMemory:
    """Stores short-term execution history and compressed repository context."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    ast_cache: dict[str, Any] = field(default_factory=dict)
