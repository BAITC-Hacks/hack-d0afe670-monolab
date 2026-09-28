#!/usr/bin/env bash
# Run on the VPS after code is synced to ~/talap
set -euo pipefail

TALAP_ROOT="${TALAP_ROOT:-$HOME/talap}"
BACKEND="$TALAP_ROOT/backend"
FRONTEND="$TALAP_ROOT/frontend"
PORT="${PORT:-8016}"
S3_ENDPOINT="${S3_ENDPOINT:-https://object.pscloud.io}"
S3_BUCKET="${S3_BUCKET:-s3://govtech-monolab}"

echo "==> Talap VPS setup (port $PORT)"

# Free space from failed pip installs (4GB user quota)
rm -rf /tmp/pip-unpack-* /tmp/tmp* 2>/dev/null || true
find "$TALAP_ROOT" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# Rootless Docker (hackathon VPS)
if ! docker ps &>/dev/null; then
  systemctl --user start docker 2>/dev/null || true
  sleep 2
fi

# Postgres via docker compose
cd "$TALAP_ROOT"
docker compose up -d
sleep 3

# Python venv
# Python deps (minimal install for 4GB disk quota)
bash "$TALAP_ROOT/deploy/vps/install_deps.sh" "$BACKEND"
cd "$BACKEND"
source .venv/bin/activate

# Download model weights from S3 if missing
mkdir -p training/weights
if [[ ! -f training/weights/best.pt ]]; then
  AWS_BIN="${AWS_BIN:-$HOME/.awscli/bin/aws}"
  if [[ -x "$AWS_BIN" ]]; then
    echo "==> Downloading model from S3..."
    "$AWS_BIN" s3 cp "$S3_BUCKET/models/best.pt" training/weights/best.pt \
      --endpoint-url "$S3_ENDPOINT"
  else
    echo "WARN: training/weights/best.pt missing and aws cli not at $AWS_BIN"
  fi
fi

# Restore DB seed if empty
CONTRACTS=$(docker compose exec -T db psql -U talap -d talap -tAc \
  "SELECT COUNT(*) FROM road_contracts" 2>/dev/null || echo "0")
CONTRACTS=$(echo "$CONTRACTS" | tr -d '[:space:]')
if [[ "${CONTRACTS:-0}" == "0" ]] && [[ -f /tmp/talap_seed.dump ]]; then
  echo "==> Restoring database seed..."
  cat /tmp/talap_seed.dump | docker compose exec -T db pg_restore -U talap -d talap \
    --data-only --disable-triggers 2>/dev/null || true
fi

# Init schema + seed contracts (idempotent)
source .venv/bin/activate
PYTHONPATH=. python -c "import asyncio; from app.db import init_db; asyncio.run(init_db())"
CONTRACTS=$(docker compose exec -T db psql -U talap -d talap -tAc \
  "SELECT COUNT(*) FROM road_contracts" 2>/dev/null | tr -d '[:space:]')
if [[ "${CONTRACTS:-0}" == "0" ]] && [[ -f /tmp/talap_seed.dump ]]; then
  echo "==> Restoring contract seed..."
  cat /tmp/talap_seed.dump | docker compose exec -T db pg_restore -U talap -d talap \
    --data-only --disable-triggers 2>/dev/null || true
fi

echo "==> Setup complete. Start with: deploy/vps/start.sh"
