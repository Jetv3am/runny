#!/usr/bin/env bash
# Run the API (FastAPI) and the web UI (Next.js) together.
#   Ctrl+C stops both. If either one crashes, the other is stopped too.
# Usage: make dev   (or ./scripts/dev.sh)
# Ports can be overridden: API_PORT=8200 WEB_PORT=3100 make dev
# The web UI listens on this Mac only. To open it from a phone on the same Wi-Fi:
#   WEB_HOST=0.0.0.0 make dev     (exposes your data to everyone on that network!)
#
# Written for macOS's stock bash 3.2 (no `wait -n`), hence the polling loop.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_PORT="${API_PORT:-8100}"
WEB_PORT="${WEB_PORT:-3000}"
WEB_HOST="${WEB_HOST:-127.0.0.1}"  # Next.js defaults to all interfaces; health data stays local

# Wire the two servers to each other so custom ports actually work: the web app must
# know where the API is, and the API must allow the web app's origin (direct uploads).
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://127.0.0.1:$API_PORT}"
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT}"

API_PID=""
WEB_PID=""

fail() {
  echo "dev: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "'$1' not found. $2"
}

require_free_port() {
  local port=$1 name=$2
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "port $port ($name) is already in use. Stop that process or set ${name}_PORT."
  fi
}

# Kill a process and all of its descendants (uv -> uvicorn reloader -> worker, npm -> next).
# The awk log labellers are skipped: they exit on their own once their server's output
# closes, which also guarantees the last log lines get printed.
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    [ "$(ps -o comm= -p "$child" 2>/dev/null)" = "awk" ] && continue
    kill_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
}

# Safety net for orphans: if a parent died hard, its children are re-parented and
# kill_tree can't find them. Preflight proved these ports were free at startup, so
# whatever listens on them now was started by this script.
free_port() {
  local pid
  for pid in $(lsof -t -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null); do
    kill -TERM "$pid" 2>/dev/null || true
  done
}

cleanup() {
  trap - INT TERM EXIT
  echo
  echo "dev: stopping servers..."
  [ -n "$API_PID" ] && kill_tree "$API_PID"
  [ -n "$WEB_PID" ] && kill_tree "$WEB_PID"
  free_port "$API_PORT"
  free_port "$WEB_PORT"
  wait 2>/dev/null
  echo "dev: stopped."
}

# Ctrl+C / kill: clean up and exit (bash would otherwise resume the supervise loop).
# Exit 0: stopping a dev server is the normal way to end it, not an error.
on_signal() {
  cleanup
  exit 0
}

# Prefix each output line so the two logs are distinguishable.
label() {
  awk -v tag="$1" '{ print tag " " $0; fflush() }'
}

# --- Preflight ---------------------------------------------------------------
require_command uv "Install it: brew install uv"
require_command npm "Install Node.js: brew install node"
require_free_port "$API_PORT" API
require_free_port "$WEB_PORT" WEB

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "dev: installing frontend dependencies (first run only)..."
  (cd "$ROOT/frontend" && npm install) || fail "npm install failed"
fi

trap on_signal INT TERM
trap cleanup EXIT

# --- Start -------------------------------------------------------------------
# `uv run` syncs the backend venv automatically, so no separate install step.
(cd "$ROOT/backend" && exec uv run uvicorn coach.main:app --reload --port "$API_PORT") \
  > >(label "[api]") 2>&1 &
API_PID=$!

(cd "$ROOT/frontend" && exec npm run dev -- --port "$WEB_PORT" --hostname "$WEB_HOST") \
  > >(label "[web]") 2>&1 &
WEB_PID=$!

echo "dev: API -> http://127.0.0.1:$API_PORT/docs"
echo "dev: App -> http://localhost:$WEB_PORT   (Ctrl+C to stop both)"

# --- Supervise: exit as soon as either server dies ---------------------------
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "$API_PID" 2>/dev/null; then
  echo "dev: API server exited - shutting down the web server too." >&2
else
  echo "dev: web server exited - shutting down the API too." >&2
fi
exit 1
