"""Integration and unit tests for the core orchestrator agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from lathe.cli import app
from lathe.config import RoleConfig
from lathe.llm.base import LLMClient
from lathe.llm.types import Message, StreamChunk, ToolCall, ToolSpec
from lathe.orchestrator.agent import Agent
from lathe.orchestrator.events import (
    AgentEvent,
    AgentHaltEvent,
    DiffEvent,
    EventBus,
    FinalAnswerEvent,
    NudgeEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from lathe.safety.permissions import PermissionEngine, PermissionMode
from lathe.ui.agent_view import TerminalAgentUI


class ScriptedFakeLLMClient(LLMClient):
    """Deterministic LLM test double that yields canned streaming responses turn by turn."""

    def __init__(
        self,
        responses: list[list[StreamChunk]],
        model: str = "fake-coder-model",
    ) -> None:
        super().__init__(
            role_config=RoleConfig(
                backend="ollama",
                model=model,
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
            chunks = self.responses[self.turn_index]
            self.turn_index += 1
            for chunk in chunks:
                yield chunk
        else:
            yield StreamChunk(delta="Final default answer.", done=True)


@pytest.fixture
def test_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory for agent testing."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.mark.asyncio
async def test_agent_full_edit_and_test_integration(test_workspace: Path) -> None:
    """Agent reads a buggy file, edits it to fix bug, runs tests, and delivers answer."""
    # 1. Setup buggy file and test file in workspace
    calc_file = test_workspace / "calc.py"
    calc_file.write_text("def add(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8")

    test_file = test_workspace / "test_calc.py"
    test_file.write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    # 2. Setup scripted LLM responses:
    # Turn 1: Thoughts + ToolCall to read_file
    # Turn 2: Thoughts + ToolCall to edit_file
    # Turn 3: Thoughts + ToolCall to run_shell (pytest)
    # Turn 4: Final textual answer without tool calls
    scripted_turns: list[list[StreamChunk]] = [
        # Turn 1: read calc.py
        [
            StreamChunk(delta="I will read calc.py to inspect the add function.\n"),
            StreamChunk(
                tool_call_delta=ToolCall(
                    id="call_read_1",
                    name="read_file",
                    arguments={"path": "calc.py"},
                ),
                done=True,
            ),
        ],
        # Turn 2: edit calc.py to fix subtraction to addition
        [
            StreamChunk(delta="Now I will edit calc.py to replace subtraction with addition.\n"),
            StreamChunk(
                tool_call_delta=ToolCall(
                    id="call_edit_1",
                    name="edit_file",
                    arguments={
                        "path": "calc.py",
                        "edits": [{"old": "return a - b", "new": "return a + b"}],
                    },
                ),
                done=True,
            ),
        ],
        # Turn 3: run tests
        [
            StreamChunk(delta="Running pytest test_calc.py to verify the fix.\n"),
            StreamChunk(
                tool_call_delta=ToolCall(
                    id="call_test_1",
                    name="run_shell",
                    arguments={"command": "python3 -m unittest test_calc.py"},
                ),
                done=True,
            ),
        ],
        # Turn 4: final answer
        [
            StreamChunk(
                delta="Successfully fixed `calc.py` and verified that tests pass.",
                done=True,
            ),
        ],
    ]

    fake_client = ScriptedFakeLLMClient(scripted_turns)

    # Setup permissions: auto-allow write and shell for this test
    perm_engine = PermissionEngine(test_workspace, mode=PermissionMode.YOLO)

    # Setup event recording
    recorded_events: list[AgentEvent] = []
    event_bus = EventBus()
    event_bus.subscribe(lambda e: recorded_events.append(e))

    agent = Agent(
        client=fake_client,
        workspace_root=test_workspace,
        permission_engine=perm_engine,
        event_bus=event_bus,
    )

    # Execute agent
    task_prompt = "Fix the addition bug in calc.py and verify tests pass."
    result = await agent.run(task_prompt)

    # 3. Assertions
    assert "Successfully fixed" in result

    # File on disk must be updated
    updated_content = calc_file.read_text(encoding="utf-8")
    assert "return a + b" in updated_content
    assert "return a - b" not in updated_content

    # Check event order
    event_types = [type(e) for e in recorded_events]
    assert ThinkingEvent in event_types
    assert ToolStartEvent in event_types
    assert ToolEndEvent in event_types
    assert DiffEvent in event_types
    assert FinalAnswerEvent in event_types

    # Verify specific tool calls occurred
    tool_starts = [e for e in recorded_events if isinstance(e, ToolStartEvent)]
    assert [t.tool_name for t in tool_starts] == ["read_file", "edit_file", "run_shell"]

    # Verify DiffEvent captured the change
    diff_events = [e for e in recorded_events if isinstance(e, DiffEvent)]
    assert len(diff_events) == 1
    assert diff_events[0].path == "calc.py"
    assert "+    return a + b" in diff_events[0].diff


@pytest.mark.asyncio
async def test_agent_parallel_read_tools(test_workspace: Path) -> None:
    """Verify that multiple read-only tool calls in a single turn run concurrently in parallel."""
    (test_workspace / "file1.txt").write_text("content 1\n")
    (test_workspace / "file2.txt").write_text("content 2\n")

    scripted_turns: list[list[StreamChunk]] = [
        [
            StreamChunk(
                tool_call_delta=ToolCall(
                    id="call_read_1",
                    name="read_file",
                    arguments={"path": "file1.txt"},
                )
            ),
            StreamChunk(
                tool_call_delta=ToolCall(
                    id="call_read_2",
                    name="read_file",
                    arguments={"path": "file2.txt"},
                ),
                done=True,
            ),
        ],
        [
            StreamChunk(delta="Read both files in parallel.", done=True),
        ],
    ]

    fake_client = ScriptedFakeLLMClient(scripted_turns)
    recorded_events: list[AgentEvent] = []
    event_bus = EventBus()
    event_bus.subscribe(lambda e: recorded_events.append(e))

    agent = Agent(
        client=fake_client,
        workspace_root=test_workspace,
        event_bus=event_bus,
    )

    result = await agent.run("Read file1.txt and file2.txt")
    assert "Read both files in parallel" in result

    # Both tools must have executed
    tool_ends = [e for e in recorded_events if isinstance(e, ToolEndEvent)]
    assert len(tool_ends) == 2
    assert {te.arguments["path"] for te in tool_ends} == {"file1.txt", "file2.txt"}
    assert all(te.result.ok for te in tool_ends)


@pytest.mark.asyncio
async def test_agent_loop_detection_nudge_and_stop(test_workspace: Path) -> None:
    """Verify loop detection: identical tool call 3 times injects nudge, 5 times stops loop."""
    (test_workspace / "target.txt").write_text("sample content\n")

    # Script 6 identical tool calls
    identical_call = ToolCall(
        id="call_loop",
        name="read_file",
        arguments={"path": "target.txt"},
    )

    scripted_turns: list[list[StreamChunk]] = [
        [StreamChunk(tool_call_delta=identical_call, done=True)],
        [StreamChunk(tool_call_delta=identical_call, done=True)],
        [StreamChunk(tool_call_delta=identical_call, done=True)],  # 3rd -> Nudge
        [StreamChunk(tool_call_delta=identical_call, done=True)],
        [StreamChunk(tool_call_delta=identical_call, done=True)],  # 5th -> Stop
    ]

    fake_client = ScriptedFakeLLMClient(scripted_turns)
    recorded_events: list[AgentEvent] = []
    event_bus = EventBus()
    event_bus.subscribe(lambda e: recorded_events.append(e))

    agent = Agent(
        client=fake_client,
        workspace_root=test_workspace,
        event_bus=event_bus,
    )

    result = await agent.run("Keep reading target.txt")

    # Verify halt occurred
    assert "Loop detected" in result or "repeated" in result

    # Verify NudgeEvent was emitted at 3rd repetition
    nudges = [e for e in recorded_events if isinstance(e, NudgeEvent)]
    assert any(n.repetition_count == 3 for n in nudges)
    assert any(n.repetition_count == 5 for n in nudges)

    # Verify AgentHaltEvent emitted
    halt_events = [e for e in recorded_events if isinstance(e, AgentHaltEvent)]
    assert len(halt_events) == 1
    assert "Loop detected" in halt_events[0].reason


@pytest.mark.asyncio
async def test_agent_max_steps_limit(test_workspace: Path) -> None:
    """Verify agent stops when max_agent_steps limit is reached."""
    (test_workspace / "step.txt").write_text("data\n")

    # Create distinct calls that don't trigger loop detection
    scripted_turns: list[list[StreamChunk]] = [
        [
            StreamChunk(
                tool_call_delta=ToolCall(
                    id=f"c_{i}",
                    name="read_file",
                    arguments={"path": "step.txt", "start_line": i + 1},
                ),
                done=True,
            )
        ]
        for i in range(10)
    ]

    fake_client = ScriptedFakeLLMClient(scripted_turns)
    recorded_events: list[AgentEvent] = []
    event_bus = EventBus()
    event_bus.subscribe(lambda e: recorded_events.append(e))

    agent = Agent(
        client=fake_client,
        workspace_root=test_workspace,
        event_bus=event_bus,
        max_steps=3,
    )

    result = await agent.run("Perform 10 steps")
    assert "maximum allowed steps (3)" in result

    halt_events = [e for e in recorded_events if isinstance(e, AgentHaltEvent)]
    assert len(halt_events) == 1
    assert "maximum allowed steps (3)" in halt_events[0].reason


@pytest.mark.asyncio
async def test_agent_fallback_tool_protocol(test_workspace: Path) -> None:
    """Verify fallback <tool_call> block parsing and execution."""
    (test_workspace / "hello.py").write_text("print('hello world')\n")

    fallback_scripted_turns: list[list[StreamChunk]] = [
        [
            StreamChunk(
                delta=(
                    "I will read hello.py using tool call format.\n"
                    "<tool_call>\n"
                    '{"name": "read_file", "arguments": {"path": "hello.py"}}\n'
                    "</tool_call>"
                ),
                done=True,
            )
        ],
        [
            StreamChunk(
                delta="The file contains print('hello world'). Done!",
                done=True,
            )
        ],
    ]

    # Model name that defaults to fallback protocol
    fake_client = ScriptedFakeLLMClient(fallback_scripted_turns, model="deepseek-ai/DeepSeek-R1")

    agent = Agent(
        client=fake_client,
        workspace_root=test_workspace,
    )

    result = await agent.run("Inspect hello.py")
    assert "The file contains print('hello world')" in result


def test_terminal_agent_ui_rendering(test_workspace: Path) -> None:
    """Test that TerminalAgentUI handles all events gracefully without crashing."""
    console = Console(record=True)
    ui = TerminalAgentUI(console=console)
    bus = EventBus()
    ui.attach(bus)

    # Emit all event types
    asyncio.run(bus.emit(ThinkingEvent(content="Analyzing the workspace structure...")))
    asyncio.run(
        bus.emit(
            ToolStartEvent(
                tool_id="1",
                tool_name="read_file",
                arguments={"path": "main.py"},
                risk_level="read",
            )
        )
    )
    asyncio.run(
        bus.emit(
            DiffEvent(
                path="main.py",
                diff="--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-old\n+new",
            )
        )
    )
    asyncio.run(
        bus.emit(
            NudgeEvent(
                message="Repetition warning",
                repetition_count=3,
                tool_name="read_file",
            )
        )
    )
    asyncio.run(bus.emit(FinalAnswerEvent(content="# Task Done\nAll operations verified.")))

    output = console.export_text()
    assert "read_file" in output
    assert "Diff: main.py" in output
    assert "Task Done" in output


def test_cli_one_shot_routing() -> None:
    """Test that lathe CLI routes arbitrary string task to one-shot execution."""
    runner = CliRunner()
    # Mock run_one_shot so it doesn't need real LLM in CLI unit test
    called_tasks: list[str] = []

    import lathe.orchestrator.agent as agent_mod

    orig_run_one_shot = agent_mod.run_one_shot

    def mock_run_one_shot(task: str, auto: bool = False, yolo: bool = False) -> str:
        called_tasks.append(task)
        return "Task finished"

    agent_mod.run_one_shot = mock_run_one_shot  # type: ignore[assignment]
    try:
        res = runner.invoke(app, ["write unit tests for calculator"])
        assert res.exit_code == 0
        assert called_tasks == ["write unit tests for calculator"]
    finally:
        agent_mod.run_one_shot = orig_run_one_shot  # type: ignore[assignment]
