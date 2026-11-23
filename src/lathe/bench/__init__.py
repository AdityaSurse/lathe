"""Evaluation harness for assessing model coding correctness and latency on Lathe mini-bench."""

from lathe.bench.evaluator import (
    evaluate_c_task,
    evaluate_python_task,
    evaluate_task_solution,
    evaluate_tool_task,
)
from lathe.bench.models import (
    BenchmarkSuiteResult,
    BenchTask,
    ModelBenchSummary,
    TaskResult,
)
from lathe.bench.report import (
    generate_benchmark_chart,
    render_benchmark_table,
    save_benchmark_json,
)
from lathe.bench.runner import (
    run_benchmark_suite,
    run_model_benchmark,
    run_task_evaluation,
)
from lathe.bench.tasks import ALL_BENCH_TASKS

__all__ = [
    "ALL_BENCH_TASKS",
    "BenchmarkSuiteResult",
    "BenchTask",
    "ModelBenchSummary",
    "TaskResult",
    "evaluate_c_task",
    "evaluate_python_task",
    "evaluate_task_solution",
    "evaluate_tool_task",
    "generate_benchmark_chart",
    "render_benchmark_table",
    "run_benchmark_suite",
    "run_model_benchmark",
    "run_task_evaluation",
    "save_benchmark_json",
]
