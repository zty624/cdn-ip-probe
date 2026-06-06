#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -d webui/frontend/node_modules ]]; then
  echo "missing webui/frontend/node_modules; run: cd webui/frontend && npm install" >&2
  exit 1
fi

uv run uvicorn webui.server:app --host 127.0.0.1 --port "${WEBUI_PORT:-8765}" --reload &
api_pid=$!

cd webui/frontend
npm run dev -- --host 127.0.0.1 --port "${VITE_PORT:-5173}"

kill "$api_pid" >/dev/null 2>&1 || true
