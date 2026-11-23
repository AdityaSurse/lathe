"""Unit tests for benchmark table rendering, JSON persistence, and PNG chart generation."""

from pathlib import Path

from lathe.bench.models import BenchmarkSuiteResult, ModelBenchSummary, TaskResult
from lathe.bench.report import (
    generate_benchmark_chart,
    render_benchmark_table,
    save_benchmark_json,
)


def make_dummy_suite_result() -> BenchmarkSuiteResult:
    """Helper creating sample benchmark suite metrics."""
    m1 = ModelBenchSummary(
        model="Qwen/Qwen2.5-Coder-1.5B",
        total_tasks=30,
        passed_tasks=21,
        pass_rate=70.0,
        avg_tokens_per_sec=45.2,
        avg_latency_s=1.2,
        tool_success_rate=90.0,
        task_results=[TaskResult("t1", "m1", True, 1.0, 50, 50.0)],
    )
    m2 = ModelBenchSummary(
        model="Qwen/Qwen2.5-1.5B-Instruct",
        total_tasks=30,
        passed_tasks=18,
        pass_rate=60.0,
        avg_tokens_per_sec=42.0,
        avg_latency_s=1.3,
        tool_success_rate=80.0,
        task_results=[TaskResult("t1", "m2", True, 1.0, 50, 50.0)],
    )
    m3 = ModelBenchSummary(
        model="lathe-qwen-1.5b-merged",
        total_tasks=30,
        passed_tasks=24,
        pass_rate=80.0,
        avg_tokens_per_sec=46.5,
        avg_latency_s=1.1,
        tool_success_rate=100.0,
        task_results=[TaskResult("t1", "m3", True, 1.0, 50, 50.0)],
    )
    return BenchmarkSuiteResult(
        timestamp="20261123_120000",
        label="Lathe mini-bench",
        models=[m1, m2, m3],
        tasks_count=30,
    )


def test_render_benchmark_table():
    """Render Rich comparison table."""
    suite = make_dummy_suite_result()
    table = render_benchmark_table(suite)
    assert table is not None
    assert "Lathe mini-bench" in table.title


def test_save_benchmark_json(tmp_path: Path):
    """Serialize benchmark telemetry to JSON."""
    suite = make_dummy_suite_result()
    saved_file = save_benchmark_json(suite, output_dir=tmp_path)
    assert saved_file.exists()
    assert saved_file.name == "20261123_120000.json"
    content = saved_file.read_text(encoding="utf-8")
    assert "Lathe mini-bench" in content
    assert "lathe-qwen-1.5b-merged" in content


def test_generate_benchmark_chart(tmp_path: Path):
    """Generate valid PNG bar chart in target output path."""
    suite = make_dummy_suite_result()
    chart_path = tmp_path / "bench.png"
    result_path = generate_benchmark_chart(suite, output_path=chart_path)

    assert result_path.exists()
    data = result_path.read_bytes()
    # PNG signature: 89 50 4E 47 0D 0A 1A 0A
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) > 100
