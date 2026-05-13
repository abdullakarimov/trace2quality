.PHONY: help setup dev stop test test-coverage lint format clean migrate migrate-docker docker-up docker-down docker-build demo migrate-data

help:
	@echo "Trace2Quality (t2q) - Developer Makefile"
	@echo ""
	@echo "Native development (recommended):"
	@echo "  make setup        - Create venv, install deps, copy .env.example"
	@echo "  make dev          - Start app natively (no background dependencies)"
	@echo "  make stop         - Kill background dev processes"
	@echo "  make migrate      - Run Alembic migrations (native)"
	@echo ""
	@echo "Code quality:"
	@echo "  make test         - Run test suite"
	@echo "  make test-coverage- Run tests with coverage report"
	@echo "  make lint         - Run ruff + mypy"
	@echo "  make format       - Format code (black + isort)"
	@echo "  make clean        - Remove caches and build artifacts"
	@echo ""
	@echo "Docker (optional):"
	@echo "  make docker-up    - Start Docker Compose stack"
	@echo "  make docker-down  - Stop Docker Compose stack"
	@echo "  make docker-build - Build Docker images"
	@echo ""
	@echo "Utilities:"
	@echo "  make demo         - Run demo script"
	@echo "  make migrate-data - Print legacy data migration instructions"

# ---------------------------------------------------------------------------
# Native development
# ---------------------------------------------------------------------------

VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn
ALEMBIC := $(VENV)/bin/alembic

setup:
	@echo "==> Creating virtual environment..."
	python3 -m venv $(VENV)
	@echo "==> Installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@[ -f .env ] || cp .env.example .env
	mkdir -p data/artifacts data/cache
	@echo ""
	@echo "✓ Setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env and fill in your API tokens"
	@echo "  2. Run:          make migrate && make dev"

dev: migrate
	@echo "==> Starting Trace2Quality (native)..."
	@echo "   App  → http://localhost:8000"
	@echo "   Docs → http://localhost:8000/docs"
	@echo "   Press Ctrl-C to stop."
	PYTHONPATH=$(PWD) $(UVICORN) apps.app.main:app --reload --port 8000

stop:
	-pkill -f "uvicorn apps.app.main"
	@echo "✓ Dev processes stopped"

migrate:
	@mkdir -p data
	PYTHONPATH=$(PWD) $(ALEMBIC) -c infra/migrations/alembic.ini upgrade head
	@echo "✓ Migrations complete"

# ---------------------------------------------------------------------------
# Tests / quality
# ---------------------------------------------------------------------------

test:
	PYTHONPATH=$(PWD) $(VENV)/bin/pytest apps packages -v

test-coverage:
	PYTHONPATH=$(PWD) $(VENV)/bin/pytest apps packages -v --cov=apps --cov=packages --cov-report=html
	@echo "✓ Coverage report: htmlcov/index.html"

lint:
	$(VENV)/bin/ruff check apps packages
	$(VENV)/bin/mypy apps packages

format:
	$(VENV)/bin/black apps packages
	$(VENV)/bin/isort apps packages

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete 2>/dev/null; true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null; true
	@echo "✓ Cache cleaned"

# ---------------------------------------------------------------------------
# Docker (optional convenience path)
# ---------------------------------------------------------------------------

docker-up:
	docker-compose up -d
	@echo "✓ Docker stack started — http://localhost:8000"

docker-down:
	docker-compose down

docker-build:
	docker-compose build

# Kept for backwards compat
up: docker-up
down: docker-down
build: docker-build
logs:
	docker-compose logs -f

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

demo:
	PYTHONPATH=$(PWD) $(PYTHON) scripts/demo.py

migrate-data:
	@echo "Run: python scripts/migrate_legacy_data.py --source <old_data_dir>"
	@echo "Example: PYTHONPATH=$(PWD) $(PYTHON) scripts/migrate_legacy_data.py --source ../old_spec2test/data --dry-run"

.DEFAULT_GOAL := help
