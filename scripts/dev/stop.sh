#!/usr/bin/env bash
# scripts/dev/stop.sh — Stop natively-running Trace2Quality processes
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PID_DIR="$REPO_ROOT/.dev-pids"

green() { printf '\033[0;32m%s\033[0m\n' "$*"; }

kill_pid() {
  local file="$1" name="$2"
  if [ -f "$file" ]; then
    local pid
    pid=$(cat "$file")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && green "  Stopped $name (pid $pid)"
    fi
    rm -f "$file"
  fi
}

kill_pid "$PID_DIR/app.pid" "FastAPI app"

# Belt-and-suspenders: also kill by pattern in case PIDs drifted
pkill -f "uvicorn apps.app.main" 2>/dev/null || true

green "✓ Dev processes stopped"
