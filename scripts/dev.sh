#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/kan-scrape-back"
FRONTEND_DIR="$ROOT_DIR/kan-scrape-front"
VITE_HOST="${KAN_SCRAPE_VITE_HOST:-127.0.0.1}"

backend_pid=""
frontend_pid=""

cleanup() {
  trap - SIGINT SIGTERM EXIT
  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
  fi
  if [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}

trap cleanup SIGINT SIGTERM EXIT

echo "Starting backend at http://localhost:8000"
(
  cd "$BACKEND_DIR"
  uv run uvicorn app.main:app --reload
) &
backend_pid=$!

echo "Starting frontend at http://$VITE_HOST:5173"
(
  cd "$FRONTEND_DIR"
  pnpm exec vite --host "$VITE_HOST"
) &
frontend_pid=$!

wait "$backend_pid" "$frontend_pid"
