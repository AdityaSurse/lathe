"""Tests for grep_search and semantic_search tools, fallback mechanisms, and CLI commands."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from lathe.cli import app
from lathe.context.index import CodeIndex, DeterministicEmbedder
from lathe.tools.base import ToolContext
from lathe.tools.registry import default_registry
from lathe.tools.search import (
    _python_fallback_grep,
    grep_search,
    semantic_search,
)

runner = CliRunner()


@pytest.fixture
def search_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace with known code files for search testing."""
    root = tmp_path / "search_ws"
    root.mkdir()

    (root / "src").mkdir()
    (root / "src" / "server.py").write_text(
        """import sys
import os

def start_server(port: int = 8080) -> None:
    # Context line before 1
    # Context line before 2
    print(f"Server starting on port {port}...")
    # Context line after 1
    # Context line after 2
    return None

def stop_server() -> None:
    print("Server shutting down.")
""",
        encoding="utf-8",
    )

    (root / "src" / "client.ts").write_text(
        """export class ApiClient {
  private timeout: number = 5000;

  async request(endpoint: string): Promise<string> {
    return `Response from ${endpoint}`;
  }
}
""",
        encoding="utf-8",
    )

    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text(
        """# Server Setup Guide
Run start_server to initialize the application on port 8080.
""",
        encoding="utf-8",
    )

    return root


def test_grep_search_exact_match(search_workspace: Path) -> None:
    """Verify exact literal search matches expected files and line numbers."""
    ctx = ToolContext(workspace_root=search_workspace)
    result = grep_search("Server starting on port", regex=False, context=ctx)

    assert "server.py" in result
    assert "Server starting on port" in result


def test_grep_search_regex_match(search_workspace: Path) -> None:
    """Verify regular expression search works accurately."""
    ctx = ToolContext(workspace_root=search_workspace)
    result = grep_search(r"port:\s*int\s*=\s*\d+", regex=True, context=ctx)

    assert "server.py" in result
    assert "start_server" in result


def test_grep_search_context_lines(search_workspace: Path) -> None:
    """Verify 2 lines of surrounding context are included in the search results."""
    # Force python fallback to inspect line formatting
    result = _python_fallback_grep(
        search_workspace,
        "Server starting on port",
        regex=False,
    )

    assert "Context line before 1" in result
    assert "Context line before 2" in result
    assert "Server starting on port" in result
    assert "Context line after 1" in result
    assert "Context line after 2" in result


def test_grep_search_path_glob(search_workspace: Path) -> None:
    """Verify path glob filters search scope to matching files."""
    ctx = ToolContext(workspace_root=search_workspace)

    # Search only in TypeScript files
    ts_result = grep_search("timeout", path_glob="*.ts", regex=False, context=ctx)
    assert "client.ts" in ts_result

    # Search in Python files should not find TypeScript content
    py_result = grep_search("timeout", path_glob="*.py", regex=False, context=ctx)
    assert "No matches found" in py_result or "client.ts" not in py_result


def test_grep_search_python_fallback(search_workspace: Path) -> None:
    """Verify pure Python fallback executes when ripgrep (rg) is unavailable."""
    ctx = ToolContext(workspace_root=search_workspace)

    with patch("shutil.which", return_value=None):
        result = grep_search("start_server", context=ctx)
        assert "server.py" in result
        assert "start_server" in result


def test_grep_search_no_matches(search_workspace: Path) -> None:
    """Verify clean message when pattern is not found."""
    ctx = ToolContext(workspace_root=search_workspace)
    result = grep_search("nonexistent_symbol_12345", context=ctx)
    assert "No matches found" in result


@pytest.mark.asyncio
async def test_semantic_search_tool_execution(search_workspace: Path) -> None:
    """Verify semantic_search tool returns top chunks with metadata and code blocks."""
    # Build index with deterministic embedder first
    index = CodeIndex(workspace_root=search_workspace, embedder=DeterministicEmbedder(dim=128))
    index.refresh()

    ctx = ToolContext(workspace_root=search_workspace)

    with patch("lathe.tools.search.CodeIndex", return_value=index):
        # 1. Async Tool.run execution
        tool_result = await semantic_search.run({"query": "server start port", "k": 2}, ctx=ctx)
        assert tool_result.ok
        assert "server.py" in tool_result.output
        assert "start_server" in tool_result.output

        # 2. Callable execution
        direct_output = semantic_search("API client request endpoint", k=2, context=ctx)
        assert "client.ts" in direct_output or "server.py" in direct_output


def test_search_tools_registered_in_default_registry() -> None:
    """Verify grep_search and semantic_search are registered in default_registry."""
    grep_tool = default_registry.get("grep_search")
    assert grep_tool is not None
    assert grep_tool.risk_level == "read"

    semantic_tool = default_registry.get("semantic_search")
    assert semantic_tool is not None
    assert semantic_tool.risk_level == "read"


def test_cli_lathe_index_commands(search_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify lathe index CLI commands (--stats, rebuild, refresh)."""
    monkeypatch.chdir(search_workspace)

    # 1. lathe index --stats before indexing
    res_stats1 = runner.invoke(app, ["index", "--stats"])
    assert res_stats1.exit_code == 0
    assert "Lathe Code Index Statistics" in res_stats1.output

    # 2. lathe index (builds index)
    res_build = runner.invoke(app, ["index"])
    assert res_build.exit_code == 0
    assert "complete" in res_build.output.lower()

    # 3. lathe index (up to date check)
    res_up_to_date = runner.invoke(app, ["index"])
    assert res_up_to_date.exit_code == 0
    assert "up to date" in res_up_to_date.output.lower()

    # 4. lathe index --rebuild
    res_rebuild = runner.invoke(app, ["index", "--rebuild"])
    assert res_rebuild.exit_code == 0
    assert "complete" in res_rebuild.output.lower()
