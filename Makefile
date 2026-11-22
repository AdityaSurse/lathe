.PHONY: install lint test run

install:
	uv sync --all-groups
	chflags -R nohidden .venv 2>/dev/null || true

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

test:
	uv run pytest tests/ -v

run:
	uv run lathe doctor
