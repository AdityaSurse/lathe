.PHONY: install lint test run

install:
	uv sync --all-groups
	chflags -R nohidden .venv 2>/dev/null || true

lint:
	chflags -R nohidden .venv 2>/dev/null || true
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

test:
	chflags -R nohidden .venv 2>/dev/null || true
	uv run pytest tests/ -v

run:
	chflags -R nohidden .venv 2>/dev/null || true
	uv run lathe doctor
