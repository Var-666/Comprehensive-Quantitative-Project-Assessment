#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && ../.venv/bin/alembic upgrade head)
api_port="${API_PORT:-8000}"
(cd backend && LLM_ALLOW_LOCAL_HTTP_CREDENTIALS="${LLM_ALLOW_LOCAL_HTTP_CREDENTIALS:-true}" exec ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$api_port" --reload --reload-dir app) &
api_pid=$!
(cd frontend && API_PROXY_TARGET="http://127.0.0.1:$api_port" exec ./node_modules/.bin/vite --host 127.0.0.1) &
ui_pid=$!
worker_pid=""
if [[ "${START_REMINDER_WORKER:-1}" == "1" ]]; then
  (cd backend && exec ../.venv/bin/python -m app.worker) &
  worker_pid=$!
fi
trap 'kill "$api_pid" "$ui_pid" ${worker_pid:+"$worker_pid"} 2>/dev/null || true' EXIT INT TERM
echo "前端 http://127.0.0.1:5173 · API文档 http://127.0.0.1:$api_port/docs"
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$ui_pid" 2>/dev/null && { [[ -z "$worker_pid" ]] || kill -0 "$worker_pid" 2>/dev/null; }; do sleep 1; done
exit 1
