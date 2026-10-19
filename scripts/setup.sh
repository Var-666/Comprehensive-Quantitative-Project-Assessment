#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python_exec="${PYTHON_BIN:-python3}"
"$python_exec" -m venv .venv
.venv/bin/pip install -r backend/requirements.lock.txt
npm --prefix frontend ci
(cd backend && ../.venv/bin/alembic upgrade head)
echo "工程初始化完成。运行 ./scripts/dev.sh；模拟数据需显式运行 ./scripts/seed.sh。"
