"""Tool registry providing filesystem, shell, diff, search, and testing capabilities."""

from typing import Any, Protocol


class Tool(Protocol):
    """Protocol for executable workspace tools."""

    name: str
    description: str

    def execute(self, **kwargs: Any) -> Any:
        """Execute the tool operation."""
        ...
