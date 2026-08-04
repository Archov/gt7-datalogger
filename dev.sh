#!/usr/bin/env bash
# One-shot dev environment: backend API with auto-reload (:8000) + frontend
# with hot reload (:5173) in a single terminal. Ctrl-C stops both.
# Settings come from .env (simulated telemetry by default).
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x backend/.venv/bin/python ]]; then
  echo "backend venv missing — creating it..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -e "backend[dev]"
fi
if [[ ! -d frontend/node_modules ]]; then
  echo "frontend deps missing — installing..."
  npm --prefix frontend install --no-fund --no-audit
fi
if [[ ! -d node_modules ]]; then
  echo "dev runner missing — installing..."
  npm install --no-fund --no-audit
fi

# Refresh the built frontend so :8000 serves current code, not a stale dist
# (dist/ is gitignored and only updated by this build).
echo "building frontend..."
npm --prefix frontend run build

echo
echo "  backend  → http://localhost:8000  (API + built frontend)"
echo "  frontend → http://localhost:5173  (hot reload — use this one)"
echo

exec npm run dev
