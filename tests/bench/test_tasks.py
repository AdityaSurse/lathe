"""Unit tests for the 30 built-in coding tasks in Lathe mini-bench."""

from lathe.bench.tasks import ALL_BENCH_TASKS


def test_all_bench_tasks_count():
    """Verify exactly 30 coding tasks are defined."""
    assert len(ALL_BENCH_TASKS) == 30


def test_task_languages_and_fields():
    """Verify task metadata integrity."""
    python_tasks = [t for t in ALL_BENCH_TASKS if t.language == "python"]
    c_tasks = [t for t in ALL_BENCH_TASKS if t.language == "c"]
    tool_tasks = [t for t in ALL_BENCH_TASKS if t.is_tool_task]

    assert len(python_tasks) == 20
    assert len(c_tasks) == 7
    assert len(tool_tasks) == 3

    ids = [t.id for t in ALL_BENCH_TASKS]
    assert len(ids) == len(set(ids)), "Task IDs must be globally unique"

    for t in ALL_BENCH_TASKS:
        assert t.prompt.strip(), f"Task {t.id} has empty prompt"
        assert t.entry_point.strip(), f"Task {t.id} has empty entry point"


def test_reference_python_solutions():
    """Sample reference implementations pass their own unit tests."""
    from lathe.bench.evaluator import evaluate_python_task

    # 1. Fibonacci
    fib_code = """
def fibonacci(n: int) -> int:
    if n <= 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
"""
    task_fib = next(t for t in ALL_BENCH_TASKS if t.id == "py_fib")
    passed, err = evaluate_python_task(fib_code, task_fib.test_code)
    assert passed is True, f"Fibonacci reference failed: {err}"

    # 2. Palindrome
    pal_code = """
def is_palindrome(s: str) -> bool:
    clean = [c.lower() for c in s if c.isalnum()]
    return clean == clean[::-1]
"""
    task_pal = next(t for t in ALL_BENCH_TASKS if t.id == "py_palindrome")
    passed, err = evaluate_python_task(pal_code, task_pal.test_code)
    assert passed is True, f"Palindrome reference failed: {err}"
