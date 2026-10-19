#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && ../.venv/bin/ruff check app tests && ../.venv/bin/ruff format --check app tests && ../.venv/bin/pytest -q && ../.venv/bin/alembic check)
npm --prefix frontend run format:check
npm --prefix frontend run build
