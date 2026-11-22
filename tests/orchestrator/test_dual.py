"""Integration tests for the DualAgent orchestrator (Phase 17)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from rich.console import Console

from lathe.config import RoleConfig, load_config
from lathe.llm.base import LLMClient
from lathe.llm.types import Message, StreamChunk, ToolSpec
from lathe.orchestrator.dual import (
    DualAgent,
    Plan,
    PlanRevision,
    PlanStep,
    extract_json_block,
)
from lathe.orchestrator.events import (
    AgentEvent,
    AgentHaltEvent,
    EventBus,
    FinalAnswerEvent,
    PlanCreatedEvent,
    PlanRevisedEvent,
    StepDoneEvent,
    StepStartedEvent,
)
from lathe.safety.permissions import PermissionEngine, PermissionMode
from lathe.ui.commands import handle_mode
from lathe.ui.status import SessionStats


class ScriptedFakePlanner(LLMClient):
    """Deterministic Planner LLM client yielding canned JSON plans and revisions."""

    def __init__(self, responses: list[str]) -> None:
        super().__init__(
            role_config=RoleConfig(
                backend="ollama",
                model="fake-planner-r1",
                temperature=0.0,
                max_tokens=2048,
                context_window=8192,
            )
        )
        self.responses = list(responses)
        self.turn_index = 0
        self.recorded_turns: list[list[Message]] = []

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        self.recorded_turns.append(list(messages))
        if self.turn_index < len(self.responses):
            text = self.responses[self.turn_index]
            self.turn_index += 1
            yield StreamChunk(delta=text, done=True)
        else:
            yield StreamChunk(
                delta=json.dumps({"revised": False, "explanation": "No changes", "steps": []}),
                done=True,
            )


class ScriptedFakeCoder(LLMClient):
    """Deterministic Coder LLM client yielding tool calls or final responses."""

    def __init__(self, turns: list[list[StreamChunk]]) -> None:
        super().__init__(
            role_config=RoleConfig(
                backend="ollama",
                model="fake-coder-qwen",
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
            yield StreamChunk(delta="Step completed successfully.", done=True)


@pytest.fixture
def test_dual_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace for dual orchestrator testing."""
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "main.py").write_text("# initial main\n", encoding="utf-8")
    return ws


def test_plan_pydantic_schema() -> None:
    """Verify Plan, PlanStep, and PlanRevision schema validation."""
    step = PlanStep(
        id=1,
        title="Create auth module",
        files_to_read=["src/config.py"],
        files_to_change=["src/auth.py"],
        instructions="Implement JWT auth",
        done_when="pytest passes",
    )
    assert step.id == 1
    assert step.status == "pending"

    plan = Plan(
        goal="Add authentication",
        steps=[step],
        risks=["Token expiration edge case"],
    )
    assert plan.goal == "Add authentication"
    assert len(plan.steps) == 1
    assert plan.risks == ["Token expiration edge case"]

    rev = PlanRevision(revised=True, explanation="Added tests", steps=[step])
    assert rev.revised is True
    assert rev.steps[0].title == "Create auth module"


def test_json_block_extraction() -> None:
    """Extract JSON from raw text or markdown code fences."""
    raw = '{"goal": "test", "steps": [], "risks": []}'
    assert extract_json_block(raw) == raw

    fenced = f"Here is the plan:\n```json\n{raw}\n```\nHope it helps!"
    assert extract_json_block(fenced) == raw


@pytest.mark.asyncio
async def test_planner_retries_once_on_invalid_json(test_dual_workspace: Path) -> None:
    """Planner retries once when initial response is invalid JSON."""
    valid_plan = {
        "goal": "Build helper",
        "steps": [
            {
                "id": 1,
                "title": "Create helper.py",
                "files_to_read": [],
                "files_to_change": ["helper.py"],
                "instructions": "Write helper function",
                "done_when": "File exists",
            }
        ],
        "risks": [],
    }

    # Turn 1: Malformed JSON, Turn 2: Valid JSON
    planner = ScriptedFakePlanner(
        [
            "This is not JSON at all! { broken",
            f"```json\n{json.dumps(valid_plan)}\n```",
        ]
    )
    coder = ScriptedFakeCoder([])

    agent = DualAgent(
        planner_client=planner,
        coder_client=coder,
        workspace_root=test_dual_workspace,
        auto_approve=True,
    )

    plan = await agent.generate_plan("Build helper")
    assert plan.goal == "Build helper"
    assert len(plan.steps) == 1
    assert planner.turn_index == 2
    # Verify retry prompt was sent
    retry_msg = planner.recorded_turns[1][-1].content
    assert "failed validation" in retry_msg


@pytest.mark.asyncio
async def test_user_rejection_halts_dual_agent(test_dual_workspace: Path) -> None:
    """DualAgent halts if the user rejects the plan."""
    plan_dict = {
        "goal": "Dangerous refactor",
        "steps": [
            {
                "id": 1,
                "title": "Delete files",
                "files_to_read": [],
                "files_to_change": [],
                "instructions": "Delete everything",
                "done_when": "Everything gone",
            }
        ],
        "risks": ["Data loss"],
    }

    planner = ScriptedFakePlanner([json.dumps(plan_dict)])
    coder = ScriptedFakeCoder([])
    event_bus = EventBus()
    events: list[AgentEvent] = []
    event_bus.subscribe(events.append)

    agent = DualAgent(
        planner_client=planner,
        coder_client=coder,
        workspace_root=test_dual_workspace,
        event_bus=event_bus,
        approval_callback=lambda p: "n",  # Reject plan
    )

    res = await agent.run("Dangerous task")
    assert "rejected by user" in res.lower()
    halt_events = [e for e in events if isinstance(e, AgentHaltEvent)]
    assert len(halt_events) == 1
    assert "rejected by user" in halt_events[0].reason.lower()


@pytest.mark.asyncio
async def test_user_can_edit_plan_via_callback(test_dual_workspace: Path) -> None:
    """DualAgent accepts a modified Plan returned by the approval callback."""
    plan_dict = {
        "goal": "Original goal",
        "steps": [
            {
                "id": 1,
                "title": "Original step",
                "files_to_read": [],
                "files_to_change": [],
                "instructions": "Original instructions",
                "done_when": "Done",
            }
        ],
        "risks": [],
    }

    def edit_callback(p: Plan) -> Plan:
        # Edit the plan to add a new step
        p.steps.append(
            PlanStep(
                id=2,
                title="Edited step 2",
                files_to_read=[],
                files_to_change=[],
                instructions="Execute step 2",
                done_when="Done",
            )
        )
        return p

    planner = ScriptedFakePlanner([json.dumps(plan_dict)])
    coder = ScriptedFakeCoder(
        [
            [StreamChunk(delta="Step 1 complete.", done=True)],
            [StreamChunk(delta="Step 2 complete.", done=True)],
        ]
    )

    agent = DualAgent(
        planner_client=planner,
        coder_client=coder,
        workspace_root=test_dual_workspace,
        approval_callback=edit_callback,
    )

    res = await agent.run("Task with edited plan")
    assert "Task Complete" in res
    assert "Edited step 2" in res


@pytest.mark.asyncio
async def test_dual_orchestrator_full_integration(test_dual_workspace: Path) -> None:
    """Full end-to-end execution of DualAgent with two fake LLMs and plan revision."""
    initial_plan = {
        "goal": "Implement greeting module",
        "steps": [
            {
                "id": 1,
                "title": "Create greeting.py",
                "files_to_read": [],
                "files_to_change": ["greeting.py"],
                "instructions": "Create greeting.py with greet(name) function returning Hello",
                "done_when": "greeting.py exists",
            },
            {
                "id": 2,
                "title": "Draft test",
                "files_to_read": ["greeting.py"],
                "files_to_change": ["test_greeting.py"],
                "instructions": "Create test_greeting.py with test_greet asserting greeting",
                "done_when": "test_greeting.py exists",
            },
        ],
        "risks": ["None"],
    }

    # Planner revision after step 1: updates step 2 with refined instructions
    revision_payload = {
        "revised": True,
        "explanation": "Refined step 2 instructions after reviewing greeting.py implementation",
        "steps": [
            {
                "id": 2,
                "title": "Draft and run test",
                "files_to_read": ["greeting.py"],
                "files_to_change": ["test_greeting.py"],
                "instructions": "Write comprehensive unit tests in test_greeting.py",
                "done_when": "test_greeting.py exists",
            }
        ],
    }

    planner = ScriptedFakePlanner(
        [
            json.dumps(initial_plan),
            json.dumps(revision_payload),
        ]
    )

    # Coder responses:
    # Step 1: Tool call to write_file, then final response
    # Step 2: Tool call to write_file, then final response
    step1_tool_call_json = (
        '<tool_call>{"name": "write_file", "arguments": {"path": "greeting.py", '
        '"content": "def greet(name: str) -> str:\\n    return f\\"Hello, {name}!\\"\\n"}}'
        "</tool_call>"
    )
    step2_tool_call_json = (
        '<tool_call>{"name": "write_file", "arguments": {"path": "test_greeting.py", '
        '"content": "from greeting import greet\\n\\ndef test_greet():\\n'
        '    assert greet(\\"World\\") == \\"Hello, World!\\"\\n"}}</tool_call>'
    )

    coder = ScriptedFakeCoder(
        [
            # Step 1: Turn 1 (ToolCall)
            [StreamChunk(delta=f"Creating greeting.py.\n{step1_tool_call_json}")],
            # Step 1: Turn 2 (Final)
            [StreamChunk(delta="Created greeting.py successfully.", done=True)],
            # Step 2: Turn 1 (ToolCall)
            [StreamChunk(delta=f"Creating test_greeting.py.\n{step2_tool_call_json}")],
            # Step 2: Turn 2 (Final)
            [StreamChunk(delta="Created test_greeting.py successfully.", done=True)],
        ]
    )

    # Setup permissions and events
    console = Console(record=True)
    pe = PermissionEngine(test_dual_workspace, mode=PermissionMode.AUTO, console=console)
    event_bus = EventBus()
    events: list[AgentEvent] = []
    event_bus.subscribe(events.append)

    agent = DualAgent(
        planner_client=planner,
        coder_client=coder,
        permission_engine=pe,
        workspace_root=test_dual_workspace,
        event_bus=event_bus,
        console=console,
        auto_approve=True,
    )

    report = await agent.run("Implement greeting module")
    assert "Implement greeting module" in report

    # Assert workspace files were created by coder
    assert (test_dual_workspace / "greeting.py").exists()
    assert "def greet" in (test_dual_workspace / "greeting.py").read_text(encoding="utf-8")
    assert (test_dual_workspace / "test_greeting.py").exists()

    # Assert events emitted
    plan_created_events = [e for e in events if isinstance(e, PlanCreatedEvent)]
    assert len(plan_created_events) == 1
    assert plan_created_events[0].plan_goal == "Implement greeting module"
    assert plan_created_events[0].total_steps == 2

    step_started_events = [e for e in events if isinstance(e, StepStartedEvent)]
    assert len(step_started_events) == 2
    assert step_started_events[0].step_number == 1
    assert step_started_events[0].title == "Create greeting.py"
    assert step_started_events[1].step_number == 2
    assert step_started_events[1].title == "Draft and run test"  # revised title

    step_done_events = [e for e in events if isinstance(e, StepDoneEvent)]
    assert len(step_done_events) == 2
    assert step_done_events[0].success is True
    assert step_done_events[1].success is True

    plan_revised_events = [e for e in events if isinstance(e, PlanRevisedEvent)]
    assert len(plan_revised_events) == 1
    assert "Refined step 2" in plan_revised_events[0].explanation

    final_events = [e for e in events if isinstance(e, FinalAnswerEvent)]
    assert len(final_events) == 1
    assert "Implement greeting module" in final_events[0].content


@pytest.mark.asyncio
async def test_focused_context_passed_to_coder(test_dual_workspace: Path) -> None:
    """Coder model receives a focused context with instructions, files, and previous summaries."""
    plan_dict = {
        "goal": "Two-step task",
        "steps": [
            {
                "id": 1,
                "title": "Step 1 Title",
                "files_to_read": ["main.py"],
                "files_to_change": ["output.txt"],
                "instructions": "Perform step 1 specifically",
                "done_when": "Step 1 done",
            },
            {
                "id": 2,
                "title": "Step 2 Title",
                "files_to_read": ["output.txt"],
                "files_to_change": [],
                "instructions": "Perform step 2 specifically",
                "done_when": "Step 2 done",
            },
        ],
        "risks": [],
    }

    planner = ScriptedFakePlanner([json.dumps(plan_dict)])
    coder = ScriptedFakeCoder(
        [
            [StreamChunk(delta="Step 1 done.", done=True)],
            [StreamChunk(delta="Step 2 done.", done=True)],
        ]
    )

    agent = DualAgent(
        planner_client=planner,
        coder_client=coder,
        workspace_root=test_dual_workspace,
        auto_approve=True,
    )

    await agent.run("Run focused task")

    # Inspect Coder's recorded turns
    # Turn 0 was Step 1
    step1_user_msg = coder.recorded_turns[0][-1].content
    assert "Step 1 Title" in step1_user_msg
    assert "Perform step 1 specifically" in step1_user_msg
    assert "@main.py" in step1_user_msg
    assert "@output.txt" in step1_user_msg

    # Turn 1 was Step 2
    step2_user_msg = coder.recorded_turns[1][-1].content
    assert "Step 2 Title" in step2_user_msg
    assert "Perform step 2 specifically" in step2_user_msg
    assert "Previous Steps Summary" in step2_user_msg
    assert "Step 1 done" in step2_user_msg


def test_slash_command_mode_switch() -> None:
    """Slash command /mode switches between single and dual modes."""
    cfg = load_config(require_secrets=False)
    stats = SessionStats()
    console = Console()

    # Switch to dual
    handle_mode(["dual"], cfg, stats, console)
    assert cfg.settings.mode == "dual"

    # Switch back to single
    handle_mode(["single"], cfg, stats, console)
    assert cfg.settings.mode == "single"
