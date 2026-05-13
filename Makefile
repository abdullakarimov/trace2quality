.PHONY: help setup up down logs test test-coverage lint format clean migrate build demo migrate-data shell-app shell-worker logs-app logs-worker

help:
	@echo "Trace2Quality (t2q) - Developer Makefile"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  setup         - Initialize development environment"
	@echo "  up            - Start Docker Compose stack"
	@echo "  down          - Stop Docker Compose stack"
	@echo "  logs          - Tail logs from all services"
	@echo "  logs-app      - Tail logs from app service"
	@echo "  logs-worker   - Tail logs from worker service"
	@echo "  test          - Run test suite"
	@echo "  test-coverage - Run tests with coverage report"
	@echo "  lint          - Run linters (ruff, mypy)"
	@echo "  format        - Format code (black, isort)"
	@echo "  clean         - Remove cache, test artifacts"
	@echo "  migrate       - Run database migrations"
	@echo "  build         - Build Docker images"
	@echo "  demo          - Run demonstration script"
	@echo "  migrate-data  - Migrate legacy spec2test data"
	@echo "  shell-app     - Open shell in app container"
	@echo "  shell-worker  - Open shell in worker container"

setup:
	@echo "Setting up Trace2Quality development environment..."
	cp .env.example .env
	mkdir -p data/artifacts data/cache
	python -m pip install --upgrade pip
	pip install -e ".[dev]"
	@echo "✓ Setup complete!"

up:
	docker-compose up -d
	@echo "✓ Services started"
	@echo "  - App: http://localhost:8000"
	@echo "  - Redis: localhost:6379"

down:
	docker-compose down
	@echo "✓ Services stopped"

logs:
	docker-compose logs -f

logs-app:
	docker-compose logs -f app

logs-worker:
	docker-compose logs -f worker

test:
	pytest apps packages -v

test-coverage:
	pytest apps packages -v --cov=apps --cov=packages --cov-report=html
	@echo "✓ Coverage report generated at htmlcov/index.html"

lint:
	@echo "Running linters..."
	ruff check apps packages
	mypy apps packages
	@echo "✓ Linting complete"

format:
	@echo "Formatting code..."
	black apps packages
	isort apps packages
	@echo "✓ Formatting complete"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	@echo "✓ Cache cleaned"

migrate:
	docker-compose exec app alembic upgrade head
	@echo "✓ Migrations complete"

build:
	docker-compose build
	@echo "✓ Images built"

demo:
	@echo "Running Trace2Quality demo..."
	python scripts/demo.py
	@echo "✓ Demo complete"

migrate-data:
	@echo "Run: python scripts/migrate_legacy_data.py --source <old_data_dir>"
	@echo "Example: python scripts/migrate_legacy_data.py --source ../old_spec2test/data --dry-run"

shell-app:
	docker-compose exec app bash

shell-worker:
	docker-compose exec worker bash

.DEFAULT_GOAL := help
