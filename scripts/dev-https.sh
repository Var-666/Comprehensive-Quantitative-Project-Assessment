#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python scripts/init_llm_security.py
api_port="${API_PORT:-8002}"
ui_port="${UI_PORT:-5175}"
security_dir="$PWD/.local-secrets"
(cd backend && ../.venv/bin/alembic upgrade head)
(cd backend && COOKIE_SECURE=true ALLOWED_ORIGINS="https://127.0.0.1:$ui_port,https://127.0.0.1:$api_port" exec ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$api_port" --ssl-keyfile "$security_dir/localhost.key" --ssl-certfile "$security_dir/localhost.crt") &
api_pid=$!
(cd frontend && API_PROXY_TARGET="https://127.0.0.1:$api_port" VITE_TLS_CERT_FILE="$security_dir/localhost.crt" VITE_TLS_KEY_FILE="$security_dir/localhost.key" NODE_EXTRA_CA_CERTS="$security_dir/localhost.crt" exec ./node_modules/.bin/vite --host 127.0.0.1 --port "$ui_port") &
ui_pid=$!
trap 'kill "$api_pid" "$ui_pid" 2>/dev/null || true' EXIT INT TERM
echo "本机HTTPS： https://127.0.0.1:$ui_port/settings/llm · 本地证书仅供开发，生产须使用企业可信证书。"
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$ui_pid" 2>/dev/null; do sleep 1; done
exit 1
