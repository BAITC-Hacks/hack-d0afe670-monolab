#!/usr/bin/env bash
# VPS-friendly deps: CPU torch, minimal ultralytics runtime (4GB disk quota)
set -euo pipefail
export PIP_NO_CACHE_DIR=1

BACKEND="${1:-$HOME/talap/backend}"
cd "$BACKEND"

rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip wheel
pip cache purge 2>/dev/null || true

echo "==> CPU PyTorch"
pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cpu

echo "==> API stack"
pip install -q \
  fastapi "uvicorn[standard]" httpx python-dotenv pydantic \
  "sqlalchemy[asyncio]" asyncpg openai reportlab Pillow python-multipart

echo "==> CV runtime (minimal — no polars/scipy/matplotlib)"
pip install -q ultralytics --no-deps
pip install -q opencv-python-headless pyyaml psutil requests

echo "==> Done"
pip show fastapi torch ultralytics opencv-python-headless | grep -E '^Name:|^Version:'
