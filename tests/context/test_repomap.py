"""Tests for tree-sitter symbol indexing, Personalized PageRank, and RepoMap."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lathe.cli import app
from lathe.context.repomap import (
    RepoMap,
    estimate_tokens,
    parse_file_symbols,
)
from lathe.orchestrator.agent import Agent


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Create a temporary multi-language fixture repository with definitions and refs."""
    repo = tmp_path / "fixture_repo"
    repo.mkdir()

    # 1. Python service definition
    (repo / "service.py").write_text(
        "class UserService:\n"
        "    def __init__(self, db_url: str) -> None:\n"
        "        self.db_url = db_url\n\n"
        "    def get_user(self, user_id: int) -> dict:\n"
        "        return {'id': user_id}\n\n"
        "def create_default_user() -> dict:\n"
        "    return {'id': 0}\n",
        encoding="utf-8",
    )

    # 2. Python client referencing UserService
    (repo / "client.py").write_text(
        "from service import UserService, create_default_user\n\n"
        "class ApiClient:\n"
        "    def run(self) -> None:\n"
        "        service = UserService('postgres://localhost')\n"
        "        user = service.get_user(42)\n"
        "        fallback = create_default_user()\n",
        encoding="utf-8",
    )

    # 3. TypeScript server definition
    (repo / "server.ts").write_text(
        "interface ServerConfig {\n"
        "    port: number;\n"
        "    host: string;\n"
        "}\n\n"
        "class HttpServer {\n"
        "    start(config: ServerConfig): boolean {\n"
        "        return true;\n"
        "    }\n"
        "}\n\n"
        "function bootServer(): void {}\n",
        encoding="utf-8",
    )

    # 4. Go worker definition
    (repo / "worker.go").write_text(
        "package worker\n\n"
        "type TaskQueue struct {\n"
        "    Capacity int\n"
        "}\n\n"
        "func (t *TaskQueue) Enqueue(task string) error {\n"
        "    return nil\n"
        "}\n\n"
        "func ProcessTasks() int {\n"
        "    return 1\n"
        "}\n",
        encoding="utf-8",
    )

    # 5. Rust calculator
    (repo / "math.rs").write_text(
        "struct Vector2D {\n"
        "    x: f64,\n"
        "    y: f64,\n"
        "}\n\n"
        "impl Vector2D {\n"
        "    fn magnitude(&self) -> f64 {\n"
        "        0.0\n"
        "    }\n"
        "}\n\n"
        "fn dot_product(v1: &Vector2D, v2: &Vector2D) -> f64 {\n"
        "    0.0\n"
        "}\n",
        encoding="utf-8",
    )

    # 6. C header and utility
    (repo / "buffer.c").write_text(
        "struct ByteBuffer {\n"
        "    char* data;\n"
        "    int size;\n"
        "};\n\n"
        "int allocate_buffer(int capacity) {\n"
        "    return capacity;\n"
        "}\n",
        encoding="utf-8",
    )

    # 7. Java application
    (repo / "App.java").write_text(
        "public class App {\n"
        "    public static void main(String[] args) {\n"
        "        System.out.println(1);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    return repo


def test_parse_file_symbols_across_languages(fixture_repo: Path) -> None:
    """Verify definitions, signatures, and references across Python, TS, Go, Rust, C, Java."""
    # Python
    py_fs = parse_file_symbols(fixture_repo / "service.py", "service.py")
    def_names = {d.name for d in py_fs.definitions}
    assert "UserService" in def_names
    assert "get_user" in def_names
    assert "create_default_user" in def_names
    # Check signatures contain declaration without body
    user_service_def = next(d for d in py_fs.definitions if d.name == "UserService")
    assert user_service_def.signature.startswith("class UserService:")
    assert "return" not in user_service_def.signature

    # TypeScript
    ts_fs = parse_file_symbols(fixture_repo / "server.ts", "server.ts")
    ts_names = {d.name for d in ts_fs.definitions}
    assert "ServerConfig" in ts_names
    assert "HttpServer" in ts_names
    assert "start" in ts_names
    assert "bootServer" in ts_names

    # Go
    go_fs = parse_file_symbols(fixture_repo / "worker.go", "worker.go")
    go_names = {d.name for d in go_fs.definitions}
    assert "TaskQueue" in go_names
    assert "Enqueue" in go_names
    assert "ProcessTasks" in go_names

    # Rust
    rs_fs = parse_file_symbols(fixture_repo / "math.rs", "math.rs")
    rs_names = {d.name for d in rs_fs.definitions}
    assert "Vector2D" in rs_names
    assert "magnitude" in rs_names
    assert "dot_product" in rs_names

    # C
    c_fs = parse_file_symbols(fixture_repo / "buffer.c", "buffer.c")
    c_names = {d.name for d in c_fs.definitions}
    assert "ByteBuffer" in c_names
    assert "allocate_buffer" in c_names

    # Java
    java_fs = parse_file_symbols(fixture_repo / "App.java", "App.java")
    java_names = {d.name for d in java_fs.definitions}
    assert "App" in java_names
    assert "main" in java_names


def test_reference_graph_construction(fixture_repo: Path) -> None:
    """Verify client.py -> service.py edge is formed because client references UserService."""
    rm = RepoMap(workspace_root=fixture_repo)
    file_symbols = rm.scan_workspace()
    out_edges, in_edges = rm.build_graph(file_symbols)

    assert "service.py" in out_edges.get("client.py", set())
    assert "client.py" in in_edges.get("service.py", set())


def test_personalized_pagerank_base_and_boosts(fixture_repo: Path) -> None:
    """Verify Personalized PageRank prioritizes dependencies, @file mentions, and task keywords."""
    rm = RepoMap(workspace_root=fixture_repo)
    file_symbols = rm.scan_workspace()
    out_edges, in_edges = rm.build_graph(file_symbols)

    # 1. Base ranking: service.py is a dependency of client.py, so service.py > client.py
    base_ranked = rm.personalized_pagerank(file_symbols, out_edges, in_edges)
    scores = dict(base_ranked)
    assert scores["service.py"] > scores["client.py"]

    # 2. @file boost: mentioning @client.py lifts client.py to the top
    boosted_ranked = rm.personalized_pagerank(
        file_symbols,
        out_edges,
        in_edges,
        task="Refactor api",
        mentioned_files=["client.py"],
    )
    assert boosted_ranked[0][0] == "client.py"

    # 3. Task keywords matching symbol names or paths
    math_ranked = rm.personalized_pagerank(
        file_symbols,
        out_edges,
        in_edges,
        task="Compute dot product of vector2d coordinates",
    )
    assert math_ranked[0][0] == "math.rs"

    # 4. Edited files boost
    edited_ranked = rm.personalized_pagerank(
        file_symbols,
        out_edges,
        in_edges,
        task="General maintenance",
        edited_files=["server.ts"],
    )
    assert edited_ranked[0][0] == "server.ts"


def test_repomap_token_budget_limiting(fixture_repo: Path) -> None:
    """Verify generated repository map respects configured token limits."""
    rm = RepoMap(workspace_root=fixture_repo, token_budget=50)
    map_text = rm.get_repo_map(token_budget=50)

    assert map_text != ""
    assert estimate_tokens(map_text) <= 60


def test_cache_persistence_and_invalidation(fixture_repo: Path) -> None:
    """Verify .lathe/cache/repomap.json caches entries and re-parses when modified."""
    rm = RepoMap(workspace_root=fixture_repo)
    cache_file = fixture_repo / ".lathe" / "cache" / "repomap.json"
    assert not cache_file.exists()

    # Initial scan creates cache
    rm.scan_workspace()
    assert cache_file.is_file()

    with open(cache_file, encoding="utf-8") as f:
        cache_data = json.load(f)
    assert "service.py" in cache_data
    old_mtime = cache_data["service.py"]["mtime"]

    # Sleep briefly to ensure stat mtime increments on edit
    time.sleep(0.05)
    (fixture_repo / "service.py").write_text(
        "class NewService:\n    def new_method(self) -> None:\n        pass\n",
        encoding="utf-8",
    )

    # Re-scan must update cache for modified file
    rm.scan_workspace()
    with open(cache_file, encoding="utf-8") as f:
        updated_data = json.load(f)
    assert updated_data["service.py"]["mtime"] != old_mtime
    updated_defs = {d["name"] for d in updated_data["service.py"]["definitions"]}
    assert "NewService" in updated_defs


def test_cli_lathe_map_command(fixture_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify `lathe map` CLI command outputs repository map."""
    monkeypatch.chdir(fixture_repo)
    runner = CliRunner()
    result = runner.invoke(app, ["map", "--budget", "1000"])

    assert result.exit_code == 0
    assert "service.py:" in result.output or "client.py:" in result.output
    assert "UserService" in result.output or "ApiClient" in result.output


def test_agent_system_prompt_repomap_injection(fixture_repo: Path) -> None:
    """Verify Agent injects dynamic repository map into system prompt."""
    agent = Agent(workspace_root=fixture_repo)
    tool_specs = agent.tools.get_tool_specs()
    prompt = agent._build_system_prompt("Fix the UserService bug", tool_specs, "native")

    assert "# Repository Map" in prompt
    assert "service.py:" in prompt
