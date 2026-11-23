"""Pytest configuration and test collection routing for lathe."""

from __future__ import annotations

from pathlib import Path

import pytest

# Specific directory names or top-level filenames that act as convenience aliases
ALIAS_DIRS = {"git", "checkpoints", "checkpoint", "agent", "repomap", "search"}
ALIAS_ROOT_FILES = {
    "test_git.py",
    "test_checkpoints.py",
    "test_checkpoint.py",
    "test_agent.py",
    "test_repomap.py",
    "test_tools.py",
    "test_safety.py",
    "test_search.py",
    "test_index.py",
    "test_budget.py",
    "test_dual.py",
    "test_tests.py",
    "test_review.py",
    "test_router.py",
    "test_merge.py",
    "test_bench.py",
}


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Ignore alias test paths during general test runs to prevent duplicate test executions.

    If a user explicitly runs a targeted command like `pytest tests/git` or
    `pytest tests/repomap` or `pytest tests/test_tools.py`, the alias is collected and run.
    Canonical paths under `tests/tools/`, `tests/safety/`, and `tests/context/`
    are always collected.
    """
    resolved_path = collection_path.resolve()

    # Determine if this collection path is an alias
    is_alias = False
    parts = collection_path.parts

    # 1. Alias directories: tests/git, tests/checkpoints, tests/checkpoint, tests/repomap, etc.
    for d in ALIAS_DIRS:
        if d in parts:
            is_alias = True
            break

    # 2. Top-level test files that alias tools/safety/repomap
    if (
        not is_alias
        and collection_path.name in ALIAS_ROOT_FILES
        and len(parts) >= 2
        and parts[-2] == "tests"
    ):
        is_alias = True

    if not is_alias:
        return None

    # Inspect CLI arguments
    cli_args = [arg for arg in config.args if not arg.startswith("-")]

    tests_root = (Path.cwd() / "tests").resolve()
    # Check if the user specifically targeted this alias in CLI args
    for arg in cli_args:
        arg_path = Path(arg).resolve()
        # General run targets (whole tests folder or project root) should ignore aliases
        if arg_path in (tests_root, Path.cwd()):
            continue
        # Direct match or parent/child relationship
        if arg_path == resolved_path:
            return False
        try:
            resolved_path.relative_to(arg_path)
            return False
        except ValueError:
            pass
        try:
            arg_path.relative_to(resolved_path)
            return False
        except ValueError:
            pass

    # Not explicitly targeted; ignore to avoid duplicates in `pytest` / `make test`
    return True
