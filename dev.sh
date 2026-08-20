#!/usr/bin/env bash
# One-shot dev environment: backend API with auto-reload (:8000) + frontend
# with hot reload (:5173) in a single terminal. Ctrl-C stops both.
# Settings come from .env (simulated telemetry by default).
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x backend/.venv/bin/python ]]; then
  echo "backend venv missing — creating it..."
  python3 -m venv backend/.venv
fi
# Reinstall whenever pyproject.toml is newer than the last install (or the
# stamp doesn't exist yet), so new dependencies land in the existing venv.
if [[ backend/pyproject.toml -nt backend/.venv/.deps-installed ]]; then
  echo "backend deps out of date — installing..."
  backend/.venv/bin/pip install -e "backend[dev]"
  touch backend/.venv/.deps-installed
fi
if [[ frontend/package.json -nt frontend/node_modules/.deps-installed ]]; then
  echo "frontend deps out of date — installing..."
  npm --prefix frontend install --no-fund --no-audit
  touch frontend/node_modules/.deps-installed
fi
if [[ package.json -nt node_modules/.deps-installed ]]; then
  echo "dev runner deps out of date — installing..."
  npm install --no-fund --no-audit
  touch node_modules/.deps-installed
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
