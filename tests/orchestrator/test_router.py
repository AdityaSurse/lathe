"""Unit and integration tests for TaskRouter, complexity heuristics, cheap internal jobs,
and StatsCollector.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from rich.console import Console

from lathe.config import LatheConfig, RoleConfig, SettingsConfig
from lathe.llm.base import LLMClient
from lathe.llm.types import Message, StreamChunk, ToolSpec, Usage
from lathe.orchestrator.router import (
    RoleStats,
    StatsCollector,
    TaskRouter,
    classify_by_heuristics,
    classify_with_router_model,
    generate_commit_message,
    generate_task_title,
    get_read_search_tools,
    set_stats_collector,
    summarize_for_compaction,
    track_client,
)
from lathe.tools.registry import default_registry
from lathe.ui.commands import handle_mode, handle_stats
from lathe.ui.status import SessionStats

# ---------------------------------------------------------------------------
# Test Doubles (Fake LLMs)
# ---------------------------------------------------------------------------


class ScriptedFakeRouterLLM(LLMClient):
    """Deterministic router LLM yielding pre-scripted responses."""

    def __init__(self, responses: list[str]) -> None:
        super().__init__(
            role_config=RoleConfig(
                backend="ollama",
                model="fake-router",
                temperature=0.0,
                max_tokens=512,
                context_window=4096,
            )
        )
        self.responses = list(responses)
        self.call_count = 0
        self.recorded_messages: list[list[Message]] = []

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        self.recorded_messages.append(list(messages))
        idx = self.call_count
        self.call_count += 1
        resp = self.responses[idx] if idx < len(self.responses) else "{}"
        yield StreamChunk(
            delta=resp,
            done=True,
            usage=Usage(prompt_tokens=42, completion_tokens=18, total_tokens=60, duration_ms=150.0),
        )


# ---------------------------------------------------------------------------
# Heuristic Classification Tests
# ---------------------------------------------------------------------------


def test_classify_by_heuristics_greetings_and_chat() -> None:
    """Greetings, identity questions, and conceptual inquiries classify as chat."""
    assert classify_by_heuristics("hello") == "chat"
    assert classify_by_heuristics("hi there Lathe!") == "chat"
    assert classify_by_heuristics("hey") == "chat"
    assert classify_by_heuristics("who are you?") == "chat"
    assert classify_by_heuristics("what does this repository do?") == "chat"
    assert classify_by_heuristics("how do I run tests?") == "chat"
    assert classify_by_heuristics("can you explain repo map architecture?") == "chat"
    assert classify_by_heuristics("tell me about the project architecture") == "chat"
    assert classify_by_heuristics("why is python 3.11 required?") == "chat"


def test_classify_by_heuristics_complex_keywords() -> None:
    """Explicit architectural keywords trigger complex classification."""
    assert classify_by_heuristics("refactor the permission engine") == "complex"
    assert classify_by_heuristics("build the router module") == "complex"
    assert classify_by_heuristics("migrate sqlite database to postgres") == "complex"
    assert classify_by_heuristics("rewrite parser using tree-sitter") == "complex"
    assert classify_by_heuristics("redesign the UI layout") == "complex"
    assert classify_by_heuristics("overhaul the test suite") == "complex"


def test_classify_by_heuristics_multiple_files() -> None:
    """Referencing multiple files triggers complex classification."""
    assert (
        classify_by_heuristics("update @src/main.py and @tests/test_main.py for new auth")
        == "complex"
    )
    assert classify_by_heuristics("sync changes between src/config.py and lathe.toml") == "complex"


def test_classify_by_heuristics_long_multistep() -> None:
    """Long multi-sentence/multi-step descriptions classify as complex."""
    long_prompt = (
        "We need to implement a full user authentication flow across the system.\n"
        "Step 1: Create the User model with email and hashed password.\n"
        "Step 2: Add password hashing and verification utilities.\n"
        "Step 3: Implement JWT token generation and validation middleware.\n"
        "And then ensure tests verify invalid passwords return 401."
    )
    assert len(long_prompt) > 280
    assert classify_by_heuristics(long_prompt) == "complex"


def test_classify_by_heuristics_simple_single_file() -> None:
    """Single file targeting small bug fixes or updates classifies as simple."""
    assert classify_by_heuristics("fix typo in @README.md") == "simple"
    assert classify_by_heuristics("add docstring to get_user in @users.py") == "simple"
    assert classify_by_heuristics("update version to 1.0.0 in @pyproject.toml") == "simple"
    assert classify_by_heuristics("rename variable count to total in @calc.py") == "simple"
    assert classify_by_heuristics("fix off-by-one bug in @utils.py") == "simple"


def test_classify_by_heuristics_ambiguous_returns_none() -> None:
    """Ambiguous requests with no keywords or single clear target return None."""
    # "make it faster" has no explicit file, no complex keyword, not a question
    assert classify_by_heuristics("make it faster") is None
    assert classify_by_heuristics("clean up the code") is None
    assert classify_by_heuristics("apply optimizations") is None


# ---------------------------------------------------------------------------
# Router Model JSON Classification Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_with_router_model_valid_json() -> None:
    """Router model returns structured category and reasoning."""
    client = ScriptedFakeRouterLLM(
        ['{"category": "complex", "reasoning": "Performance optimization requires refactoring."}']
    )
    res = await classify_with_router_model("optimize loop in algorithm", client)
    assert res.category == "complex"
    assert "refactoring" in res.reasoning


@pytest.mark.asyncio
async def test_classify_with_router_model_markdown_fences() -> None:
    """Router model response inside markdown code fences parses successfully."""
    client = ScriptedFakeRouterLLM(
        ['```json\n{"category": "chat", "reasoning": "Conceptual question."}\n```']
    )
    res = await classify_with_router_model("is there any benchmark?", client)
    assert res.category == "chat"


# ---------------------------------------------------------------------------
# TaskRouter Routing Decisions and Mode Dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_router_classification_and_dim_lines(tmp_path: Path) -> None:
    """TaskRouter correctly routes to chat, single, and dual modes with dim line formatting."""
    console = Console(record=True)
    router = TaskRouter(
        workspace_root=tmp_path,
        console=console,
    )

    # 1. Chat
    d_chat = await router.classify("what is this repo?")
    assert d_chat.category == "chat"
    assert d_chat.mode == "chat"
    assert d_chat.display_line == "routed: chat → read/search only"

    # 2. Simple
    d_simple = await router.classify("fix typo in @README.md")
    assert d_simple.category == "simple"
    assert d_simple.mode == "single"
    assert d_simple.display_line == "routed: simple → single mode"

    # 3. Complex
    d_complex = await router.classify("refactor entire permission engine")
    assert d_complex.category == "complex"
    assert d_complex.mode == "dual"
    assert d_complex.display_line == "routed: complex → dual mode"


@pytest.mark.asyncio
async def test_task_router_uses_llm_when_heuristics_ambiguous(tmp_path: Path) -> None:
    """TaskRouter falls back to router client when heuristics are inconclusive."""
    router_llm = ScriptedFakeRouterLLM(
        ['{"category": "simple", "reasoning": "Single function tweak."}']
    )
    router = TaskRouter(
        router_client=router_llm,
        workspace_root=tmp_path,
    )
    decision = await router.classify("make this performant")
    assert decision.category == "simple"
    assert decision.mode == "single"
    assert router_llm.call_count == 1


# ---------------------------------------------------------------------------
# Restricted Chat Tools Test
# ---------------------------------------------------------------------------


def test_get_read_search_tools() -> None:
    """Chat mode tool registry only includes read and search tools."""
    chat_tools = get_read_search_tools(default_registry)
    tool_names = {t.name for t in chat_tools.list_tools()}

    # Read and search tools present
    assert "read_file" in tool_names
    assert "list_dir" in tool_names
    assert "glob" in tool_names
    assert "grep_search" in tool_names
    assert "semantic_search" in tool_names
    assert "git_status" in tool_names

    # Write / execute tools absent
    assert "write_file" not in tool_names
    assert "edit_file" not in tool_names
    assert "run_shell" not in tool_names
    assert "run_tests" not in tool_names
    assert "git_commit" not in tool_names


# ---------------------------------------------------------------------------
# Cheap Internal Jobs Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_for_compaction() -> None:
    """Summarize older dialogue turns into bullet points using the router model."""
    client = ScriptedFakeRouterLLM(
        ["- Read src/main.py\n- Modified auth router\n- Ran pytest with 10 passes"]
    )
    messages = [
        Message(role="user", content="Please add auth"),
        Message(role="assistant", content="Reading src/main.py..."),
        Message(role="user", content="Now run tests"),
    ]
    summary = await summarize_for_compaction(messages, client)
    assert "- Read src/main.py" in summary
    assert "- Ran pytest with 10 passes" in summary


@pytest.mark.asyncio
async def test_generate_commit_message() -> None:
    """Generate Conventional Commits message from diff using router model."""
    client = ScriptedFakeRouterLLM(["feat(router): add task complexity classification"])
    diff = """
diff --git a/router.py b/router.py
new file mode 100644
+class TaskRouter:
+    pass
"""
    msg = await generate_commit_message(diff, client)
    assert msg == "feat(router): add task complexity classification"

    # Empty diff fallback
    empty_msg = await generate_commit_message("", client)
    assert empty_msg == "chore: update workspace"


@pytest.mark.asyncio
async def test_generate_task_title() -> None:
    """Generate short 3-6 word task title."""
    client = ScriptedFakeRouterLLM(["Build Dual-LLM Router Engine"])
    title = await generate_task_title(
        "Build src/lathe/orchestrator/router.py with heuristics and classification",
        client,
    )
    assert title == "Build Dual-LLM Router Engine"


# ---------------------------------------------------------------------------
# Stats Collector Tests
# ---------------------------------------------------------------------------


def test_stats_collector_metrics_and_persistence(tmp_path: Path) -> None:
    """StatsCollector tracks per-role metrics, computes tokens/sec, and saves stats.json."""
    session_id = "test_sess_123"
    collector = StatsCollector(session_id=session_id, workspace_root=tmp_path)

    # Record calls for various roles
    collector.record_call("coder", input_tokens=1000, output_tokens=250, duration_s=2.5)
    collector.record_call("coder", input_tokens=800, output_tokens=200, duration_s=1.5)
    collector.record_call("planner", input_tokens=1500, output_tokens=300, duration_s=3.0)
    collector.record_call("router", input_tokens=150, output_tokens=30, duration_s=0.5)

    coder_stats: RoleStats = collector.roles["coder"]
    assert coder_stats.calls == 2
    assert coder_stats.input_tokens == 1800
    assert coder_stats.output_tokens == 450
    assert coder_stats.total_tokens == 2250
    assert coder_stats.latency_seconds == 4.0
    assert coder_stats.tokens_per_second == 112.5
    assert coder_stats.avg_latency == 2.0

    planner_stats: RoleStats = collector.roles["planner"]
    assert planner_stats.calls == 1
    assert planner_stats.tokens_per_second == 100.0

    # Persistence verification
    stats_file = collector.get_stats_file_path()
    assert stats_file.exists()
    data = json.loads(stats_file.read_text(encoding="utf-8"))
    assert data["session_id"] == session_id
    assert data["roles"]["coder"]["calls"] == 2
    assert data["roles"]["planner"]["calls"] == 1
    assert data["total"]["calls"] == 4
    assert data["total"]["total_tokens"] == 4230


def test_stats_collector_rich_table_rendering(tmp_path: Path) -> None:
    """Rich table formatting produces columns for Role, Calls, Tokens, Latency, and TPS."""
    collector = StatsCollector(session_id="tbl_sess", workspace_root=tmp_path)
    collector.record_call("coder", 500, 100, 1.0)
    collector.record_call("reviewer", 800, 50, 0.5)

    table = collector.render_rich_table()
    assert table.title is not None
    assert "tbl_sess" in table.title
    col_names = [col.header for col in table.columns]
    assert "Role" in col_names
    assert "Calls" in col_names
    assert "Input Tokens" in col_names
    assert "Output Tokens" in col_names
    assert "Latency (s)" in col_names
    assert "Tokens/sec" in col_names


@pytest.mark.asyncio
async def test_tracking_llm_client_auto_records(tmp_path: Path) -> None:
    """TrackingLLMClient intercepts chat streaming and automatically updates StatsCollector."""
    collector = StatsCollector(session_id="tracking_sess", workspace_root=tmp_path)
    inner = ScriptedFakeRouterLLM(["Chunk one. Chunk two."])
    wrapped = track_client(inner, "router", collector=collector)

    # Stream call
    messages = [Message(role="user", content="Hello")]
    chunks: list[str] = []
    async for c in wrapped.chat(messages, stream=True):
        if c.delta:
            chunks.append(c.delta)

    assert "".join(chunks) == "Chunk one. Chunk two."
    router_stats = collector.roles["router"]
    assert router_stats.calls == 1
    assert router_stats.input_tokens == 42  # From Usage
    assert router_stats.output_tokens == 18


# ---------------------------------------------------------------------------
# UI Slash Commands & Mode Overrides Tests
# ---------------------------------------------------------------------------


def test_handle_mode_and_stats_commands(tmp_path: Path) -> None:
    """Slash commands /mode auto|single|dual and /stats execute cleanly."""
    console = Console(record=True, width=120)
    cfg = LatheConfig(settings=SettingsConfig(mode="auto"))
    stats = SessionStats()

    collector = StatsCollector(session_id="cmd_sess", workspace_root=tmp_path)
    set_stats_collector(collector)
    collector.record_call("coder", 300, 60, 0.5)

    # /mode single
    assert handle_mode(["single"], cfg, stats, console) is True
    assert cfg.settings.mode == "single"

    # /mode dual
    assert handle_mode(["dual"], cfg, stats, console) is True
    assert cfg.settings.mode == "dual"

    # /mode auto
    assert handle_mode(["auto"], cfg, stats, console) is True
    assert cfg.settings.mode == "auto"

    # /stats
    assert handle_stats([], cfg, stats, console) is True
    output = console.export_text()
    assert "Session Stats" in output
    assert "Coder" in output
    assert "Tokens/sec" in output
