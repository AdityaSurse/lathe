"""Unit tests for benchmark runner and metric aggregation."""

from collections.abc import AsyncIterator

import pytest

from lathe.bench.models import BenchTask
from lathe.bench.runner import run_model_benchmark
from lathe.config import RoleConfig
from lathe.llm.base import LLMClient
from lathe.llm.types import Message, StreamChunk, ToolSpec


class ScriptedBenchLLM(LLMClient):
    """Deterministic LLM yielding pre-configured solutions."""

    def __init__(self, responses: list[str]) -> None:
        super().__init__(
            role_config=RoleConfig(
                backend="ollama",
                model="test-model",
                temperature=0.0,
                max_tokens=2048,
            )
        )
        self.responses = list(responses)
        self.idx = 0

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        if self.idx < len(self.responses):
            text = self.responses[self.idx]
            self.idx += 1
            yield StreamChunk(delta=text, done=True)
        else:
            yield StreamChunk(delta="def fallback(): return 0", done=True)


@pytest.mark.asyncio
async def test_run_model_benchmark_metrics():
    """Verify aggregated metrics (pass@1, throughput, latency, tool accuracy)."""
    task1 = BenchTask(
        id="t1",
        name="Add",
        language="python",
        prompt="Write add(a, b)",
        entry_point="add",
        test_code="assert add(1, 2) == 3",
    )
    task2 = BenchTask(
        id="t2",
        name="Sub",
        language="python",
        prompt="Write sub(a, b)",
        entry_point="sub",
        test_code="assert sub(5, 3) == 2",
    )
    task3 = BenchTask(
        id="tool_t",
        name="Tool",
        language="tool",
        prompt="Call calc",
        entry_point="calc",
        test_code="",
        is_tool_task=True,
        expected_tool="calc",
        expected_args={"val": 42},
    )

    client = ScriptedBenchLLM(
        [
            "def add(a, b): return a + b",
            "def sub(a, b): return a - b",
            '<tool_call>{"name": "calc", "arguments": {"val": 42}}</tool_call>',
        ]
    )

    summary = await run_model_benchmark(
        model_name="mock-model",
        tasks=[task1, task2, task3],
        client=client,
    )

    assert summary.total_tasks == 3
    assert summary.passed_tasks == 3
    assert summary.pass_rate == 100.0
    assert summary.tool_success_rate == 100.0
    assert summary.avg_latency_s >= 0.0
    assert summary.avg_tokens_per_sec >= 0.0
