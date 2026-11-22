"""Benchmarking harness evaluating code generation accuracy and syntax validation."""

from dataclasses import dataclass


@dataclass
class BenchmarkSuite:
    """Suite configuration for evaluating candidate models."""

    name: str = "lathe-bench"
    tasks: list[str] = ("syntax", "refactor", "tests")  # type: ignore[assignment]
