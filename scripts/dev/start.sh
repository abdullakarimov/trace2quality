#!/usr/bin/env bash
# scripts/dev/start.sh — Start Trace2Quality natively (no Docker or external dependencies required)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$REPO_ROOT/venv"
PID_DIR="$REPO_ROOT/.dev-pids"

cd "$REPO_ROOT"

# Colour helpers
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }
red() { printf '\033[0;31m%s\033[0m\n' "$*"; }

# ── Pre-flight checks ──────────────────────────────────────────────────────

if [ ! -d "$VENV" ]; then
  red "Virtual environment not found. Run:  make setup"
  exit 1
fi

if [ ! -f "$REPO_ROOT/.env" ]; then
  yellow ".env not found — copying from .env.example"
  cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
  yellow "Edit .env with your API tokens before using integrations."
fi

# ── Migrations ─────────────────────────────────────────────────────────────

green "==> Running database migrations..."
mkdir -p "$REPO_ROOT/data"
PYTHONPATH="$REPO_ROOT" "$VENV/bin/alembic" -c infra/migrations/alembic.ini upgrade head

# ── Launch process ────────────────────────────────────────────────────────

mkdir -p "$PID_DIR"

green "==> Starting FastAPI app on http://localhost:8000 ..."
PYTHONPATH="$REPO_ROOT" "$VENV/bin/uvicorn" apps.app.main:app --reload --port 8000 \
  &>"$REPO_ROOT/logs/app.log" &
echo $! >"$PID_DIR/app.pid"

mkdir -p "$REPO_ROOT/logs"

green ""
green "✓ Trace2Quality is running"
green "   Web UI  → http://localhost:8000"
green "   API docs→ http://localhost:8000/docs"
green "   App log → tail -f logs/app.log"
green ""
green "Stop with:  scripts/dev/stop.sh"
