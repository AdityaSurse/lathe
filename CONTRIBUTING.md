# Contributing to Lathe

Thank you for contributing to Lathe! We welcome contributions ranging from bug reports and documentation enhancements to new tool implementations and architectural features.

---

## Code of Conduct

All contributors and participants are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Local Development Setup

Lathe requires **Python 3.11+** and uses [Astral uv](https://astral.sh/uv) for dependency management and environments.

### 1. Clone Repository & Setup Virtualenv
```bash
git clone https://github.com/adityasurse/lathe.git
cd lathe

# Create virtual environment with uv
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install editable package with dev and merge extras
uv pip install -e ".[dev,merge]"
```

### 2. Verify Setup
```bash
lathe doctor
```

---

## Quality Standards & CI Checks

All pull requests must pass the following checks before being merged:

```bash
# 1. Check style and linting with Ruff
uv run ruff check .

# 2. Check formatting with Ruff
uv run ruff format --check .

# 3. Check strict typing with Mypy (0 errors allowed)
uv run mypy src

# 4. Run test suite with pytest
uv run pytest
```

---

## Phase-Style Pull Request Workflow

Lathe adheres to a structured, phase-oriented development process:

1. **Focused PRs**: Scope each PR to a single milestone, feature, or bug fix. Avoid mixing unrelated refactors.
2. **Branch Naming**: Use descriptive prefixes: `feat/<name>`, `fix/<name>`, `docs/<name>`, `phase-<n>-<topic>`.
3. **Targeted Unit Tests**: Include unit tests achieving $\ge 80\%$ statement coverage for any new module or tool.
4. **Safety Boundaries**: Never weaken `PermissionEngine` regex blocklists or path confinement protections.
5. **Changelog & Documentation**: Update [CHANGELOG.md](CHANGELOG.md) and relevant guides in `docs/`.

---

## Finding Work & Issue Labels

Browse open issues on GitHub tagged with:
- `good first issue`: Accessible tasks designed for first-time contributors.
- `help wanted`: Features and enhancements seeking community design and execution.
- `bug`: Confirmed bugs and behavioral regressions.
- `documentation`: Documentation, guide, and docstring improvements.
