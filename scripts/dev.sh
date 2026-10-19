#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && ../.venv/bin/alembic upgrade head)
api_port="${API_PORT:-8000}"
(cd backend && exec ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$api_port") &
api_pid=$!
(cd frontend && API_PROXY_TARGET="http://127.0.0.1:$api_port" exec npm run dev) &
ui_pid=$!
trap 'kill "$api_pid" "$ui_pid" 2>/dev/null || true' EXIT INT TERM
echo "前端 http://127.0.0.1:5173 · API文档 http://127.0.0.1:$api_port/docs"
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$ui_pid" 2>/dev/null; do sleep 1; done
exit 1
