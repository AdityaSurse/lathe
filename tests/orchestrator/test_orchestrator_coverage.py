"""Comprehensive unit test coverage expansion for lathe.orchestrator (Phase 23).

Targets 80%+ coverage across:
- lathe.orchestrator.__init__
- lathe.orchestrator.agent
- lathe.orchestrator.dual
- lathe.orchestrator.events
- lathe.orchestrator.review
- lathe.orchestrator.router
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import lathe.orchestrator
from lathe.config import RoleConfig
from lathe.llm.base import LLMClient, LLMError
from lathe.llm.types import Message, StreamChunk
from lathe.orchestrator.agent import Agent
from lathe.orchestrator.dual import DualAgent, Plan, PlanStep
from lathe.orchestrator.review import (
    ReviewVerdict,
    StepReviewer,
    extract_review_json,
)
from lathe.orchestrator.router import (
    StatsCollector,
    classify_by_heuristics,
)
from lathe.tools.tests import TestRunResult


def test_orchestrator_package_exports() -> None:
    """Verify lathe.orchestrator top-level re-exports."""
    assert lathe.orchestrator.Agent is not None
    assert lathe.orchestrator.DualAgent is not None
    assert lathe.orchestrator.Plan is not None
    assert lathe.orchestrator.PlanStep is not None
    assert lathe.orchestrator.StepReviewer is not None
    assert lathe.orchestrator.ReviewVerdict is not None
    assert lathe.orchestrator.TaskRouter is not None
    assert lathe.orchestrator.StatsCollector is not None


def test_agent_extract_mentioned_files() -> None:
    """Agent correctly parses @file annotations from developer prompts."""
    agent = Agent()
    prompt = "Inspect @src/main.py and @tests/test_main.py then update @README.md"
    mentioned = agent._extract_mentioned_files(prompt)
    assert "src/main.py" in mentioned
    assert "tests/test_main.py" in mentioned
    assert "README.md" in mentioned


def test_extract_review_json_variations() -> None:
    """extract_review_json extracts JSON from code fences, raw text, or brace blocks."""
    json_text = '{"verdict": "approve", "issues": [], "summary": "Looks great"}'

    # Fenced
    fenced = f"Here is my review:\n```json\n{json_text}\n```\nHope it helps!"
    assert extract_review_json(fenced) == json_text

    # Raw
    assert extract_review_json(json_text) == json_text

    # With surrounding text without fences
    surrounded = f"Review outcome: {json_text}. End of review."
    assert extract_review_json(surrounded) == json_text


@pytest.mark.asyncio
async def test_reviewer_fallback_on_llm_error() -> None:
    """StepReviewer gracefully falls back to auto-approve when reviewer LLM fails."""

    class FailingReviewerLLM(LLMClient):
        def __init__(self) -> None:
            super().__init__(
                role_config=RoleConfig(
                    backend="ollama",
                    model="failing-model",
                    temperature=0.0,
                    max_tokens=256,
                    context_window=2048,
                )
            )

        async def chat(self, messages: list[Message], tools: Any = None, stream: bool = True):
            raise LLMError("Connection to reviewer model timed out")
            yield StreamChunk(delta="")

    reviewer = StepReviewer(client=FailingReviewerLLM())
    test_res = TestRunResult(command="pytest", exit_code=0, passed=1, failed=0, total=1)

    verdict = await reviewer.review_step(
        step_title="Test step",
        step_instructions="Test instructions",
        done_when="Done",
        diff="diff --git a/x.py b/x.py",
        test_results=test_res,
    )
    assert verdict.verdict == "approve"
    assert "auto-approv" in verdict.summary.lower()


def test_dual_agent_render_plan_checklist(tmp_path: Path) -> None:
    """DualAgent.render_plan_checklist renders rich table with status icons and risks."""
    console = Console(record=True)
    agent = DualAgent(workspace_root=tmp_path, console=console)

    plan = Plan(
        goal="Test rendering",
        steps=[
            PlanStep(
                id=1,
                title="Pending step",
                files_to_read=[],
                files_to_change=["a.py"],
                instructions="Step 1",
                done_when="Done",
                status="pending",
            ),
            PlanStep(
                id=2,
                title="Completed step",
                files_to_read=[],
                files_to_change=["b.py"],
                instructions="Step 2",
                done_when="Done",
                status="completed",
            ),
        ],
        risks=["High memory usage on huge repositories"],
    )

    agent.render_plan_checklist(plan)
    rendered = console.export_text()
    assert "Plan Checklist: Test rendering" in rendered
    assert "Pending step" in rendered
    assert "Completed step" in rendered
    assert "High memory usage" in rendered


def test_dual_agent_failed_review_choice_handler(tmp_path: Path) -> None:
    """_handle_failed_review_choice returns keep, undo, or takeover based on callback or input."""
    agent = DualAgent(
        workspace_root=tmp_path,
        review_choice_callback=lambda verdict: "undo",
    )
    verdict = ReviewVerdict(verdict="revise", issues=[], summary="Failed")
    choice = agent._handle_failed_review_choice(verdict, checkpoint_num=1)
    assert choice == "undo"


def test_stats_collector_telemetry(tmp_path: Path) -> None:
    """StatsCollector records calls, tokens, latency, and serializes to stats.json."""
    stats = StatsCollector(session_id="test_sess", workspace_root=tmp_path)
    stats.record_call(role="coder", input_tokens=100, output_tokens=50, duration_s=1.5)
    stats.record_call(role="coder", input_tokens=80, output_tokens=40, duration_s=1.0)
    stats.record_call(role="router", input_tokens=20, output_tokens=10, duration_s=0.2)

    total_data = stats.to_dict()["total"]
    assert total_data["calls"] == 3
    assert total_data["total_tokens"] == 300

    coder_stats = stats.roles["coder"]
    assert coder_stats.calls == 2
    assert coder_stats.input_tokens == 180
    assert coder_stats.output_tokens == 90

    # Render table to Rich console
    console = Console(record=True)
    console.print(stats.render_rich_table())
    table_text = console.export_text()
    assert "coder" in table_text.lower()
    assert "router" in table_text.lower()

    # Persistence to file
    session_file = tmp_path / "stats.json"
    stats.save(target_path=session_file)
    assert session_file.exists()
    saved_data = json.loads(session_file.read_text(encoding="utf-8"))
    assert "coder" in saved_data["roles"]


def test_task_router_heuristics_classification() -> None:
    """classify_by_heuristics accurately sorts chat, simple, and complex developer prompts."""
    # Chat questions
    assert classify_by_heuristics("What does the calculate_taxes function do?") == "chat"
    assert (
        classify_by_heuristics("Explain how dual-model planning works in this codebase") == "chat"
    )

    # Simple localized changes
    assert classify_by_heuristics("Fix typo in @README.md") == "simple"
    assert classify_by_heuristics("Update timeout in config.py") == "simple"

    # Complex multi-file refactoring or feature additions
    assert (
        classify_by_heuristics("Refactor authentication architecture across all microservices")
        == "complex"
    )
    assert (
        classify_by_heuristics("Build full OAuth2 authentication flow across all files")
        == "complex"
    )
    assert (
        classify_by_heuristics("Migrate @a.py @b.py @c.py @d.py to new database driver")
        == "complex"
    )
