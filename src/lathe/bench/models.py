"""Data models and schemas for Lathe mini-bench evaluation harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class BenchTask:
    """A coding task in the benchmark suite."""

    id: str
    name: str
    language: str  # "python", "c", or "tool"
    prompt: str
    entry_point: str
    test_code: str
    is_tool_task: bool = False
    expected_tool: str | None = None
    expected_args: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """Outcome of evaluating a model on a single benchmark task."""

    task_id: str
    model: str
    passed: bool
    latency_s: float
    tokens_generated: int
    tokens_per_sec: float
    tool_call_valid: bool | None = None
    error: str | None = None
    output: str = ""


@dataclass
class ModelBenchSummary:
    """Aggregated benchmark metrics for a single evaluated model."""

    model: str
    total_tasks: int
    passed_tasks: int
    pass_rate: float  # pass@1 percentage 0.0 - 100.0
    avg_tokens_per_sec: float
    avg_latency_s: float
    tool_success_rate: float  # percentage 0.0 - 100.0
    task_results: list[TaskResult] = field(default_factory=list)


@dataclass
class BenchmarkSuiteResult:
    """Full benchmark suite execution results across all evaluated models."""

    timestamp: str
    label: str  # "Lathe mini-bench"
    models: list[ModelBenchSummary]
    tasks_count: int

    def to_dict(self) -> dict[str, Any]:
        """Convert entire benchmark result to a serializable dictionary."""
        return {
            "timestamp": self.timestamp,
            "label": self.label,
            "tasks_count": self.tasks_count,
            "models": [asdict(m) for m in self.models],
        }
