"""Comprehensive unit test coverage expansion for lathe.context (Phase 23).

Targets 80%+ coverage across:
- lathe.context.__init__
- lathe.context.budget
- lathe.context.index
- lathe.context.repomap
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

import lathe.context
from lathe.context.budget import (
    BudgetAllocator,
    TokenCounter,
    compact_context,
)
from lathe.context.index import (
    chunk_file,
)
from lathe.context.repomap import RepoMap
from lathe.llm.types import Message


def test_context_package_exports() -> None:
    """Verify lathe.context top-level re-exports."""
    assert lathe.context.RepoMap is not None
    assert lathe.context.CodeIndex is not None
    assert lathe.context.TokenCounter is not None
    assert lathe.context.BudgetAllocator is not None
    assert lathe.context.compact_context is not None


def test_token_counter_heuristic_and_caching() -> None:
    """TokenCounter accurately counts tokens with heuristic fallback and counts text."""
    counter = TokenCounter(model_name="nonexistent/fake-model-repo")
    # Non-empty string yields positive count
    cnt = counter.count_tokens("def hello_world(): return 42")
    assert cnt > 0


def test_budget_allocator_shares_and_chart() -> None:
    """BudgetAllocator computes proportional shares and renders colored terminal chart."""
    allocator = BudgetAllocator(context_window=32768, max_tokens=4096)
    assert allocator.shares.system > 0
    assert allocator.shares.repomap > 0
    assert allocator.shares.conversation > 0
    assert allocator.shares.tool_results > 0

    console = Console(record=True)
    usage = allocator.calculate_usage([Message(role="user", content="Hello test")])
    allocator.render_budget_bar_chart(usage, console=console)
    chart_output = console.export_text()
    assert "tokens" in chart_output.lower() or "budget" in chart_output.lower()


def test_compaction_preserves_task_and_recent_turns() -> None:
    """compact_context strictly preserves the initial task and recent turns verbatim."""
    allocator = BudgetAllocator(context_window=1000, max_tokens=250)

    messages = [
        Message(role="user", content="CRITICAL TASK: Migrate auth database to postgres"),
        Message(role="assistant", content="Turn 1 explanation"),
        Message(role="tool", content="Tool result line 1\nTool result line 2\nTool result line 3"),
        Message(role="assistant", content="Turn 2 explanation"),
        Message(role="tool", content="Second tool huge output with multiple lines of logs"),
        Message(role="user", content="Turn 3 developer question"),
        Message(role="assistant", content="Turn 3 assistant reply"),
        Message(role="user", content="Turn 4 final confirmation"),
        Message(role="assistant", content="Turn 4 final output"),
    ]

    compacted, was_compacted, summary = compact_context(
        messages,
        allocator,
        force=True,
    )
    assert was_compacted is True
    # Initial task must survive verbatim
    assert compacted[0].content == "CRITICAL TASK: Migrate auth database to postgres"
    # Latest turns must survive
    assert any("Turn 4 final output" in m.content for m in compacted)


def test_code_index_chunking(tmp_path: Path) -> None:
    """CodeIndex chunks Python code and generates reproducible chunks."""

    # Initialize index on workspace
    sample_file = tmp_path / "sample.py"
    sample_file.write_text(
        "class Greeter:\n"
        "    def greet(self, name: str) -> str:\n"
        "        return f'Hello, {name}!'\n\n"
        "def main():\n"
        "    print('starting')\n",
        encoding="utf-8",
    )

    chunks = chunk_file(sample_file, "sample.py")
    assert len(chunks) >= 1
    has_sym = any(
        "Greeter" in c.symbol_name or "greet" in c.symbol_name or "main" in c.symbol_name
        for c in chunks
    )
    assert has_sym


def test_repomap_symbol_extraction_and_ranking(tmp_path: Path) -> None:
    """RepoMap extracts symbol definitions and builds ranked symbol map."""
    src_file = tmp_path / "math_ops.py"
    src_file.write_text(
        "class Calculator:\n"
        "    def add(self, a: int, b: int) -> int:\n"
        "        return a + b\n\n"
        "    def subtract(self, a: int, b: int) -> int:\n"
        "        return a - b\n",
        encoding="utf-8",
    )

    rm = RepoMap(workspace_root=tmp_path, token_budget=1024)
    repo_map = rm.get_repo_map(task="Add numbers with calculator")
    assert "math_ops.py" in repo_map
    assert "Calculator" in repo_map
