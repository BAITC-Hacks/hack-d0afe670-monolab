#!/usr/bin/env bash
# Start Talap on port 8016 (GovTech hackathon requirement)
set -euo pipefail

TALAP_ROOT="${TALAP_ROOT:-$HOME/talap}"
BACKEND="$TALAP_ROOT/backend"
PORT="${PORT:-8016}"

cd "$BACKEND"
source .venv/bin/activate
export PORT
export STATIC_DIR="$TALAP_ROOT/frontend/dist"

echo "Starting Talap on 0.0.0.0:$PORT ..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
