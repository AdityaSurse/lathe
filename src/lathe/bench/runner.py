"""Benchmark execution engine querying models and aggregating performance metrics."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from rich.console import Console

from lathe.bench.evaluator import evaluate_task_solution
from lathe.bench.models import (
    BenchmarkSuiteResult,
    BenchTask,
    ModelBenchSummary,
    TaskResult,
)
from lathe.bench.tasks import ALL_BENCH_TASKS
from lathe.config import RoleConfig
from lathe.llm.base import LLMClient
from lathe.llm.factory import get_client
from lathe.llm.types import Message

console = Console()


async def query_model_for_task(
    client: LLMClient,
    task: BenchTask,
) -> tuple[str, float, int, float]:
    """Send prompt to LLMClient, streaming response and measuring latency and throughput."""
    system_instruction = (
        "You are an expert software engineer participating in a code evaluation benchmark. "
        "Provide a clean, precise, and correct solution. Only return the requested code or block."
    )
    messages = [
        Message(role="system", content=system_instruction),
        Message(role="user", content=task.prompt),
    ]

    t0 = time.perf_counter()
    content_chunks: list[str] = []
    tokens_count = 0

    try:
        async for chunk in client.chat(messages, stream=True):
            if chunk.delta:
                content_chunks.append(chunk.delta)
                # Approximate token count by chunk words/subtokens or character ratio
                tokens_count += max(1, len(chunk.delta.split()))
    except Exception as exc:
        duration = time.perf_counter() - t0
        return f"# Model query failed: {exc}", duration, 0, 0.0

    duration = time.perf_counter() - t0
    full_output = "".join(content_chunks).strip()
    tok_per_sec = (tokens_count / duration) if duration > 0.001 else 0.0

    return full_output, duration, tokens_count, tok_per_sec


async def run_task_evaluation(
    model_name: str,
    task: BenchTask,
    client: LLMClient,
) -> TaskResult:
    """Execute a single benchmark task against a model and evaluate correctness."""
    output, latency, tokens, tps = await query_model_for_task(client, task)
    passed, error = evaluate_task_solution(task, output)

    tool_valid: bool | None = None
    if task.is_tool_task or task.language == "tool":
        tool_valid = passed

    return TaskResult(
        task_id=task.id,
        model=model_name,
        passed=passed,
        latency_s=latency,
        tokens_generated=tokens,
        tokens_per_sec=tps,
        tool_call_valid=tool_valid,
        error=error,
        output=output,
    )


async def run_model_benchmark(
    model_name: str,
    tasks: list[BenchTask],
    client: LLMClient | None = None,
    out_console: Console | None = None,
) -> ModelBenchSummary:
    """Evaluate a single model across all benchmark tasks and aggregate metrics."""
    out = out_console or console
    out.print(
        f"[bold cyan]Running Lathe mini-bench for:[/bold cyan] {model_name} ({len(tasks)} tasks)..."
    )

    # Resolve or construct client
    if client is not None:
        model_client = client
    else:
        role_cfg = RoleConfig(
            model=model_name,
            backend="ollama",
            temperature=0.0,
            max_tokens=2048,
        )
        model_client = get_client(role_cfg)

    task_results: list[TaskResult] = []
    for i, t in enumerate(tasks, 1):
        res = await run_task_evaluation(model_name, t, model_client)
        task_results.append(res)
        status_icon = "[green]✓[/green]" if res.passed else "[red]✗[/red]"
        out.print(
            f"  [{i}/{len(tasks)}] {status_icon} [bold]{t.id}[/bold] ({t.name}) - "
            f"{res.latency_s:.2f}s, {res.tokens_per_sec:.1f} t/s"
        )

    passed_count = sum(1 for r in task_results if r.passed)
    total_count = len(task_results)
    pass_rate = (passed_count / total_count * 100.0) if total_count > 0 else 0.0
    avg_tps = (
        (sum(r.tokens_per_sec for r in task_results) / total_count) if total_count > 0 else 0.0
    )
    avg_latency = (sum(r.latency_s for r in task_results) / total_count) if total_count > 0 else 0.0

    tool_results = [r for r in task_results if r.tool_call_valid is not None]
    tool_rate = (
        (sum(1 for r in tool_results if r.tool_call_valid) / len(tool_results) * 100.0)
        if tool_results
        else 100.0
    )

    return ModelBenchSummary(
        model=model_name,
        total_tasks=total_count,
        passed_tasks=passed_count,
        pass_rate=pass_rate,
        avg_tokens_per_sec=avg_tps,
        avg_latency_s=avg_latency,
        tool_success_rate=tool_rate,
        task_results=task_results,
    )


def run_benchmark_suite(
    models: list[str],
    tasks: list[BenchTask] | None = None,
    clients: dict[str, LLMClient] | None = None,
    out_console: Console | None = None,
) -> BenchmarkSuiteResult:
    """Execute the full benchmark suite over candidate models."""
    out = out_console or console
    bench_tasks = tasks if tasks is not None else ALL_BENCH_TASKS
    client_map = clients or {}

    out.print(
        "\n[bold white on bright_blue] Lathe mini-bench (Illustrative Evaluation) "
        "[/bold white on bright_blue]\n"
        f"Evaluating {len(models)} model(s) across {len(bench_tasks)} coding/tool tasks.\n"
    )

    summaries: list[ModelBenchSummary] = []
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        for m in models:
            cli = client_map.get(m)
            summary = loop.run_until_complete(
                run_model_benchmark(m, tasks=bench_tasks, client=cli, out_console=out)
            )
            summaries.append(summary)
    finally:
        loop.close()

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return BenchmarkSuiteResult(
        timestamp=ts,
        label="Lathe mini-bench",
        models=summaries,
        tasks_count=len(bench_tasks),
    )
