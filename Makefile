export PYTHONPATH := $(CURDIR)/src:$(PYTHONPATH)

.PHONY: install lint test run docs docs-build manual tapes

install:
	uv sync --all-groups --all-extras
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

docs:
	uv run --no-sync mkdocs serve

docs-build:
	uv run --no-sync mkdocs build --strict

tapes:
	@for tape in docs/manual/tapes/*.tape; do \
		(command -v vhs >/dev/null 2>&1 && vhs "$$tape") || (/opt/homebrew/bin/vhs "$$tape" 2>/dev/null || true); \
	done

manual:
	@for tape in docs/manual/tapes/*.tape; do \
		(command -v vhs >/dev/null 2>&1 && vhs "$$tape") || (/opt/homebrew/bin/vhs "$$tape" 2>/dev/null || true); \
	done
	uv run --no-sync python scripts/build_manual.py
