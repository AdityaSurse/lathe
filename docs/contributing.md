# Contributing to Lathe

Thank you for your interest in contributing to Lathe! We welcome bug fixes, documentation improvements, new tools, and architectural enhancements.

---

## Development Setup

Lathe requires **Python 3.11+** and uses [Astral uv](https://astral.sh/uv) for fast, reproducible virtual environments.

### 1. Clone the Repository
```bash
git clone https://github.com/adityasurse/lathe.git
cd lathe
```

### 2. Set Up Virtual Environment with uv
```bash
# Create virtual environment and install development dependencies
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev,merge]"
```

### 3. Verify Local Installation
```bash
lathe doctor
```

---

## Code Quality Standards

Before submitting a pull request, ensure all linters, formatters, type checks, and tests pass with zero errors:

### Linting & Formatting (Ruff)
```bash
# Check code style
uv run ruff check .

# Check formatting
uv run ruff format --check .

# Auto-format
uv run ruff format .
```

### Strict Type Checking (Mypy)
```bash
uv run mypy src
```

### Test Suite Execution (Pytest)
```bash
# Run standard test suite
uv run pytest

# Run with coverage report
uv run pytest --cov=src/lathe/tools --cov=src/lathe/safety --cov=src/lathe/orchestrator --cov=src/lathe/context --cov-report=term
```

---

## Phase-Style Pull Requests

Lathe follows a structured, milestone-driven phase development methodology. When opening a PR:
1. **Self-Contained Focus**: Keep pull requests focused on a single logical feature, tool, or bug fix.
2. **Comprehensive Unit Tests**: Accompany every new tool or orchestrator capability with targeted unit tests achieving 80%+ branch/statement coverage.
3. **No Breaking Safety Boundaries**: Never weaken `PermissionEngine` blocklists or path confinement.
4. **Update Documentation**: Update corresponding documentation in `docs/` and architectural notes in `ARCHITECTURE.md`.

---

## Issue Labels

Look for issues tagged with:
- `good first issue`: Ideal for newcomers to get familiar with Lathe's codebase.
- `help wanted`: Architectural features or tools actively seeking community implementation.
- `bug`: Confirmed bugs or test regressions.
- `documentation`: Guides, tutorials, and doc improvements.
