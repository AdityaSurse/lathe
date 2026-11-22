"""Tests for the step review module, retry loop, and single-mode self-check (Phase 18)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from lathe.config import RoleConfig
from lathe.llm.base import LLMClient
from lathe.llm.types import Message, StreamChunk, ToolSpec
from lathe.orchestrator.agent import Agent
from lathe.orchestrator.dual import DualAgent
from lathe.orchestrator.events import (
    AgentEvent,
    AgentHaltEvent,
    EventBus,
    StepReviewedEvent,
)
from lathe.orchestrator.review import StepReviewer
from lathe.safety.checkpoints import CheckpointManager
from lathe.safety.permissions import PermissionEngine, PermissionMode
from lathe.tools.tests import TestRunResult
from lathe.ui.agent_view import TerminalAgentUI


class ScriptedFakeReviewer(LLMClient):
    """Deterministic reviewer client yielding canned JSON verdicts."""

    def __init__(self, verdicts: list[dict[str, Any]]) -> None:
        super().__init__(
            role_config=RoleConfig(
                backend="ollama",
                model="fake-reviewer",
                temperature=0.0,
                max_tokens=2048,
                context_window=8192,
            )
        )
        self.verdicts = list(verdicts)
        self.turn_index = 0
        self.recorded_turns: list[list[Message]] = []

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        self.recorded_turns.append(list(messages))
        if self.turn_index < len(self.verdicts):
            raw = json.dumps(self.verdicts[self.turn_index])
            self.turn_index += 1
            yield StreamChunk(delta=raw, done=True)
        else:
            yield StreamChunk(
                delta=json.dumps(
                    {"verdict": "approve", "summary": "Default approve", "issues": []}
                ),
                done=True,
            )


class ScriptedFakeCoderLLM(LLMClient):
    """Deterministic coder LLM for step execution and retry."""

    def __init__(self, turns: list[list[StreamChunk]]) -> None:
        super().__init__(
            role_config=RoleConfig(
                backend="ollama",
                model="fake-coder",
                temperature=0.0,
                max_tokens=2048,
                context_window=8192,
            )
        )
        self.turns = list(turns)
        self.turn_index = 0
        self.recorded_turns: list[list[Message]] = []

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        self.recorded_turns.append(list(messages))
        if self.turn_index < len(self.turns):
            chunks = self.turns[self.turn_index]
            self.turn_index += 1
            for c in chunks:
                yield c
        else:
            yield StreamChunk(delta="Default finished.", done=True)


class ScriptedFakePlannerLLM(LLMClient):
    """Deterministic planner yielding plan."""

    def __init__(self, plan_dict: dict[str, Any]) -> None:
        super().__init__(
            role_config=RoleConfig(
                backend="ollama",
                model="fake-planner",
                temperature=0.0,
                max_tokens=2048,
                context_window=8192,
            )
        )
        self.plan_dict = plan_dict

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta=json.dumps(self.plan_dict), done=True)


@pytest.fixture
def review_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "main.py").write_text("# main\n", encoding="utf-8")
    return ws


@pytest.mark.asyncio
async def test_step_reviewer_approved() -> None:
    """Reviewer returns approve verdict when diff and tests pass."""
    fake_reviewer = ScriptedFakeReviewer(
        [{"verdict": "approve", "summary": "Code looks good and tests pass.", "issues": []}]
    )
    reviewer = StepReviewer(client=fake_reviewer)

    test_res = TestRunResult(
        command="pytest",
        exit_code=0,
        passed=5,
        failed=0,
        total=5,
    )

    verdict = await reviewer.review_step(
        step_title="Add helper",
        step_instructions="Write helper",
        done_when="Tests pass",
        diff="+ def helper(): pass\n",
        test_results=test_res,
    )

    assert verdict.verdict == "approve"
    assert len(verdict.issues) == 0


@pytest.mark.asyncio
async def test_step_reviewer_enforces_revise_when_tests_fail() -> None:
    """If tests fail, verdict must be 'revise' even if the LLM returned 'approve'."""
    fake_reviewer = ScriptedFakeReviewer(
        [{"verdict": "approve", "summary": "Mistaken approve", "issues": []}]
    )
    reviewer = StepReviewer(client=fake_reviewer)

    failing_test_res = TestRunResult(
        command="pytest",
        exit_code=1,
        passed=4,
        failed=1,
        total=5,
        failing_output="AssertionError: 3 != 4",
    )

    verdict = await reviewer.review_step(
        step_title="Add broken feature",
        step_instructions="Implement feature",
        done_when="Tests pass",
        diff="+ def bad(): raise RuntimeError()\n",
        test_results=failing_test_res,
    )

    assert verdict.verdict == "revise"
    assert len(verdict.issues) > 0
    assert any("Test suite failed" in iss.problem for iss in verdict.issues)


@pytest.mark.asyncio
async def test_dual_mode_step_review_and_retry(review_workspace: Path) -> None:
    """In dual mode, a 'revise' verdict causes coder to retry with feedback up to approval."""
    plan_dict = {
        "goal": "Build adder",
        "steps": [
            {
                "id": 1,
                "title": "Create add function",
                "files_to_read": [],
                "files_to_change": ["add.py"],
                "instructions": "Create add(a, b) in add.py",
                "done_when": "File exists",
            }
        ],
        "risks": [],
    }

    # Planner
    planner = ScriptedFakePlannerLLM(plan_dict)

    # Reviewer: Attempt 1 -> revise, Attempt 2 -> approve
    reviewer = ScriptedFakeReviewer(
        [
            {
                "verdict": "revise",
                "summary": "Missing type annotations on add function",
                "issues": [
                    {
                        "file": "add.py",
                        "line": 1,
                        "problem": "add function lacks type annotations",
                        "suggestion": "Add (a: int, b: int) -> int",
                    }
                ],
            },
            {
                "verdict": "approve",
                "summary": "Type annotations present; approved.",
                "issues": [],
            },
        ]
    )

    # Coder:
    # Attempt 1: writes add without types, final response
    # Attempt 2: writes add with types, final response
    coder = ScriptedFakeCoderLLM(
        [
            # Attempt 1
            [StreamChunk(delta="Created add.py without types.", done=True)],
            # Attempt 2 (Retry with feedback)
            [StreamChunk(delta="Fixed add.py with type annotations.", done=True)],
        ]
    )

    event_bus = EventBus()
    events: list[AgentEvent] = []
    event_bus.subscribe(events.append)

    agent = DualAgent(
        planner_client=planner,
        coder_client=coder,
        reviewer_client=reviewer,
        workspace_root=review_workspace,
        event_bus=event_bus,
        auto_approve=True,
    )

    report = await agent.run("Build adder")
    assert "Task Complete" in report

    # Verify review events
    review_events = [e for e in events if isinstance(e, StepReviewedEvent)]
    assert len(review_events) == 2
    assert review_events[0].verdict == "revise"
    assert review_events[1].verdict == "approve"

    # Verify coder turn 2 received review feedback
    coder_retry_prompt = coder.recorded_turns[1][-1].content
    assert "Review Feedback" in coder_retry_prompt
    assert "add function lacks type annotations" in coder_retry_prompt


@pytest.mark.asyncio
async def test_dual_mode_review_retries_exceeded_user_undo(tmp_path: Path) -> None:
    """When retries exceed 2, user choice 'undo' restores checkpoint and halts."""
    import subprocess

    # Initialize a git repo so checkpoints work
    ws = tmp_path / "repo"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=str(ws), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(ws), check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(ws), check=True)
    (ws / "base.txt").write_text("initial base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(ws), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(ws), check=True)

    plan_dict = {
        "goal": "Failing step",
        "steps": [
            {
                "id": 1,
                "title": "Buggy step",
                "files_to_read": [],
                "files_to_change": ["buggy.txt"],
                "instructions": "Do something",
                "done_when": "Done",
            }
        ],
        "risks": [],
    }

    planner = ScriptedFakePlannerLLM(plan_dict)

    # Reviewer continuously revises
    reviewer = ScriptedFakeReviewer(
        [
            {
                "verdict": "revise",
                "summary": "Fail 1",
                "issues": [{"file": "buggy.txt", "problem": "p", "suggestion": "s"}],
            },
            {
                "verdict": "revise",
                "summary": "Fail 2",
                "issues": [{"file": "buggy.txt", "problem": "p", "suggestion": "s"}],
            },
            {
                "verdict": "revise",
                "summary": "Fail 3",
                "issues": [{"file": "buggy.txt", "problem": "p", "suggestion": "s"}],
            },
        ]
    )

    coder = ScriptedFakeCoderLLM(
        [
            [StreamChunk(delta="Attempt 1", done=True)],
            [StreamChunk(delta="Attempt 2", done=True)],
            [StreamChunk(delta="Attempt 3", done=True)],
        ]
    )

    checkpoint_mgr = CheckpointManager(workspace_root=ws)
    event_bus = EventBus()
    events: list[AgentEvent] = []
    event_bus.subscribe(events.append)

    agent = DualAgent(
        planner_client=planner,
        coder_client=coder,
        reviewer_client=reviewer,
        checkpoint_manager=checkpoint_mgr,
        workspace_root=ws,
        event_bus=event_bus,
        auto_approve=True,
        review_choice_callback=lambda v: "undo",  # User chooses undo
    )

    res = await agent.run("Run failing task")
    assert "undone after failed review retries" in res
    halt_events = [e for e in events if isinstance(e, AgentHaltEvent)]
    assert len(halt_events) == 1


@pytest.mark.asyncio
async def test_single_mode_self_check(review_workspace: Path) -> None:
    """In single mode with self_check=True, agent reruns tests and prompts fix."""
    # Setup a failing test in the workspace
    (review_workspace / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (review_workspace / "test_math.py").write_text(
        "def test_fail(): assert 1 == 2\n", encoding="utf-8"
    )

    # Coder responses:
    # Turn 1: Initial answer without tool calls -> triggers self-check test failure
    # Turn 2: Coder fixes test_math.py with tool call, then Turn 3: Final answer
    fix_tool_call = (
        '<tool_call>{"name": "edit_file", "arguments": {"path": "test_math.py", '
        '"edits": [{"old": "assert 1 == 2", "new": "assert 1 == 1"}]}}</tool_call>'
    )

    coder = ScriptedFakeCoderLLM(
        [
            # Turn 1: Final answer that triggers self check failure
            [StreamChunk(delta="I have completed the task.", done=True)],
            # Turn 2: Model receives test failure feedback and fixes test_math.py
            [StreamChunk(delta=f"Fixing test.\n{fix_tool_call}")],
            # Turn 3: Final answer after fix
            [StreamChunk(delta="Now all tests pass successfully.", done=True)],
        ]
    )

    console = Console(record=True)
    pe = PermissionEngine(review_workspace, mode=PermissionMode.AUTO, console=console)
    agent = Agent(
        client=coder,
        workspace_root=review_workspace,
        permission_engine=pe,
        console=console,
        self_check=True,
    )

    final_ans = await agent.run("Fix everything")
    assert "all tests pass" in final_ans.lower()
    # Confirm test_math.py was updated and now passes
    assert "assert 1 == 1" in (review_workspace / "test_math.py").read_text(encoding="utf-8")


def test_ui_review_panel_rendering() -> None:
    """Verify TerminalAgentUI renders review panels with APPROVED and REVISE badges."""
    console = Console(record=True)
    ui = TerminalAgentUI(console=console)

    # 1. Approved event
    appr_event = StepReviewedEvent(
        step_number=1,
        step_title="Create auth module",
        verdict="approve",
        summary="All tests passed.",
        issues=[],
    )
    ui.on_event(appr_event)
    out1 = console.export_text()
    assert "APPROVED" in out1
    assert "Step [1] Create auth module" in out1

    # 2. Revise event
    rev_event = StepReviewedEvent(
        step_number=2,
        step_title="Add middleware",
        verdict="revise",
        summary="Fix type signature",
        issues=[
            {
                "file": "middleware.py",
                "line": 10,
                "problem": "Missing return type",
                "suggestion": "Add -> None",
            }
        ],
    )
    ui.on_event(rev_event)
    out2 = console.export_text()
    assert "REVISE" in out2
    assert "Step [2] Add middleware" in out2
    assert "middleware.py:10" in out2
    assert "Missing return type" in out2
