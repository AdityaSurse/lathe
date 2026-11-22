export PYTHONPATH := $(CURDIR)/src:$(PYTHONPATH)

.PHONY: install lint test run

install:
	uv sync --all-groups
	chflags -R nohidden .venv 2>/dev/null || true

lint:
	chflags -R nohidden .venv 2>/dev/null || true
	uv run --no-sync ruff check .
	uv run --no-sync ruff format --check .
	uv run --no-sync mypy src

test:
	chflags -R nohidden .venv 2>/dev/null || true
	uv run --no-sync pytest tests/ -v

run:
	chflags -R nohidden .venv 2>/dev/null || true
	uv run --no-sync lathe doctor
