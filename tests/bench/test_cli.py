"""Unit tests for the lathe bench CLI command."""

from pathlib import Path

from typer.testing import CliRunner

from lathe.bench.models import BenchmarkSuiteResult, ModelBenchSummary
from lathe.cli import app

runner = CliRunner()


def test_bench_cli_help():
    """Verify lathe bench --help output."""
    result = runner.invoke(app, ["bench", "--help"])
    assert result.exit_code == 0
    assert "Lathe mini-bench" in result.output
    assert "--limit" in result.output


def test_bench_cli_invocation(tmp_path: Path, monkeypatch):
    """Execute lathe bench with mocked suite runner."""
    monkeypatch.chdir(tmp_path)

    dummy_summary = ModelBenchSummary(
        model="fake-model",
        total_tasks=2,
        passed_tasks=2,
        pass_rate=100.0,
        avg_tokens_per_sec=50.0,
        avg_latency_s=0.5,
        tool_success_rate=100.0,
    )
    dummy_suite = BenchmarkSuiteResult(
        timestamp="20261123_120000",
        label="Lathe mini-bench",
        models=[dummy_summary],
        tasks_count=2,
    )

    monkeypatch.setattr("lathe.bench.runner.run_benchmark_suite", lambda **_: dummy_suite)

    result = runner.invoke(
        app, ["bench", "fake-model", "--limit", "2", "--output-dir", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "Lathe mini-bench" in result.output
    assert (tmp_path / "20261123_120000.json").exists()
