"""Pytest configuration and test collection routing for lathe."""

from __future__ import annotations

from pathlib import Path

import pytest

# Specific directory names or top-level filenames that act as convenience aliases
ALIAS_DIRS = {"git", "checkpoints", "checkpoint"}
ALIAS_ROOT_FILES = {"test_git.py", "test_checkpoints.py", "test_checkpoint.py"}


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Ignore alias test paths during general test runs to prevent duplicate test executions.

    If a user explicitly runs a targeted command like `pytest tests/git` or
    `pytest tests/checkpoints`, the alias is collected and run.
    Canonical paths under `tests/tools/` and `tests/safety/` are always collected.
    """
    resolved_path = collection_path.resolve()

    # Determine if this collection path is an alias
    is_alias = False
    parts = collection_path.parts

    # 1. Alias directories: tests/git, tests/checkpoints, tests/checkpoint
    for d in ALIAS_DIRS:
        if d in parts:
            is_alias = True
            break

    # 2. Top-level test files that alias tools/safety: e.g. tests/test_git.py directly under tests/
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

    # Check if the user specifically targeted this alias in CLI args
    for arg in cli_args:
        arg_path = Path(arg).resolve()
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
