#!/usr/bin/env bash
# Deploy Talap to GovTech VPS from your laptop.
# Usage: VPS_PASSWORD='...' ./deploy/vps/deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

VPS_HOST="${VPS_HOST:-82.115.43.223}"
VPS_USER="${VPS_USER:-monolab}"
VPS_DIR="${VPS_DIR:-~/talap}"
S3_ENDPOINT="${S3_ENDPOINT:-https://object.pscloud.io}"
S3_BUCKET="${S3_BUCKET:-s3://govtech-monolab}"
MODEL_LOCAL="${MODEL_LOCAL:-backend/runs/detect/training/runs/single_stage/weights/best.pt}"

SSH_TARGET="${VPS_USER}@${VPS_HOST}"
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)

_ssh() {
  if [[ -n "${VPS_PASSWORD:-}" ]] && command -v expect &>/dev/null; then
    VPS_PASSWORD="$VPS_PASSWORD" expect "$DEPLOY_DIR/ssh_cmd.exp" "$SSH_TARGET" "$1"
  else
    ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "$1"
  fi
}

_rsync() {
  if [[ -n "${VPS_PASSWORD:-}" ]] && command -v expect &>/dev/null; then
    VPS_PASSWORD="$VPS_PASSWORD" expect "$DEPLOY_DIR/rsync.exp" "$@"
  else
    rsync -avz -e "ssh ${SSH_OPTS[*]}" "$@"
  fi
}

echo "==> [1/6] Build frontend"
YANDEX_KEY="${YANDEX_MAPS_API_KEY:-}"
GOSZAKUP_TOKEN_VAL=""
SPECIALIST_KEY_VAL=""
if [[ -f backend/.env ]]; then
  [[ -z "$YANDEX_KEY" ]] && YANDEX_KEY=$(grep -E '^YANDEX_MAPS_API_KEY=' backend/.env | cut -d= -f2- || true)
  GOSZAKUP_TOKEN_VAL=$(grep -E '^GOSZAKUP_TOKEN=' backend/.env | cut -d= -f2- || true)
  SPECIALIST_KEY_VAL=$(grep -E '^SPECIALIST_API_KEY=' backend/.env | cut -d= -f2- || true)
fi
if [[ -z "$SPECIALIST_KEY_VAL" ]]; then
  echo "WARN: SPECIALIST_API_KEY missing in backend/.env — admin panel login will fail on VPS"
fi
cat > frontend/.env.production.local <<EOF
VITE_YANDEX_MAPS_API_KEY=${YANDEX_KEY}
VITE_DEMO_MODE=false
EOF
cd frontend
npm ci --silent 2>/dev/null || npm install --silent
npm run build
cd "$ROOT"

echo "==> [2/6] Upload model to S3 (if aws configured)"
AWS_BIN="${AWS_BIN:-aws}"
if [[ -f "$MODEL_LOCAL" ]] && command -v "$AWS_BIN" &>/dev/null; then
  "$AWS_BIN" s3 cp "$MODEL_LOCAL" "$S3_BUCKET/models/best.pt" --endpoint-url "$S3_ENDPOINT" \
    && echo "Model uploaded." \
    || echo "WARN: S3 upload failed — will rsync model directly if needed"
fi

echo "==> [3/6] Dump local DB seed (if postgres running)"
SEED_FILE="/tmp/talap_seed.dump"
if docker compose ps db 2>/dev/null | grep -q Up; then
  docker compose exec -T db pg_dump -U talap -d talap \
    -t road_contracts -t street_geocache --data-only -Fc > "$SEED_FILE" \
    && echo "DB seed: $(du -h "$SEED_FILE" | cut -f1)" \
    || echo "WARN: pg_dump failed"
else
  echo "SKIP: local postgres not running"
  rm -f "$SEED_FILE"
fi

echo "==> [4/6] Sync code to VPS"
_rsync --delete \
  --exclude '.git' \
  --exclude 'node_modules' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'backend/.venv' \
  --exclude 'backend/runs' \
  --exclude 'backend/training/dataset' \
  --exclude 'backend/training/dataset_*' \
  --exclude 'backend/training/sanity_output*' \
  --exclude 'backend/training/eval_output' \
  --exclude '*.pt' \
  --exclude '.env' \
  --exclude 'frontend/.env' \
  --exclude 'frontend/.env.production.local' \
  "$ROOT/" "${SSH_TARGET}:${VPS_DIR}/"

# Upload model directly (faster than S3 if aws not configured on laptop)
if [[ -f "$MODEL_LOCAL" ]]; then
  echo "==> Upload model weights"
  _ssh "mkdir -p ${VPS_DIR}/backend/training/weights"
  _rsync "$MODEL_LOCAL" "${SSH_TARGET}:${VPS_DIR}/backend/training/weights/best.pt"
fi

if [[ -f "$SEED_FILE" ]]; then
  echo "==> Upload DB seed"
  _rsync "$SEED_FILE" "${SSH_TARGET}:/tmp/talap_seed.dump"
fi

echo "==> [5/6] Write production .env on VPS"
ENV_TMP=$(mktemp)
cat > "$ENV_TMP" <<EOF
DATABASE_URL=postgresql://talap:talap@localhost:5433/talap
DATABASE_SSL=0
CORS_ORIGINS=https://monolab.govtech-kz.com
YANDEX_MAPS_API_KEY=${YANDEX_KEY}
GOSZAKUP_TOKEN=${GOSZAKUP_TOKEN_VAL}
CV_MODEL_PATH=training/weights/best.pt
CV_CONFIDENCE_THRESHOLD=0.4
USE_MODAL=false
GOV_GATEWAY=internal
MATCH_DATA_SOURCE=all
SPECIALIST_API_KEY=${SPECIALIST_KEY_VAL}
NOMINATIM_USER_AGENT=Talap/1.0 (monolab.govtech-kz.com)
EOF
_rsync "$ENV_TMP" "${SSH_TARGET}:${VPS_DIR}/backend/.env"
rm -f "$ENV_TMP"

echo "==> [6/6] Remote setup + restart"
_ssh "systemctl --user start docker 2>/dev/null; chmod +x ${VPS_DIR}/deploy/vps/*.sh && TALAP_ROOT=${VPS_DIR} bash ${VPS_DIR}/deploy/vps/setup_server.sh"

_ssh "pkill -f 'uvicorn app.main:app' 2>/dev/null || true; sleep 1; nohup ${VPS_DIR}/deploy/vps/start.sh > ${VPS_DIR}/talap.log 2>&1 & sleep 20; curl -sf http://127.0.0.1:8016/api/v1/health && echo ' Health OK' || tail -40 ${VPS_DIR}/talap.log"

echo ""
echo "Deploy complete: https://monolab.govtech-kz.com"
echo "Admin panel:  https://monolab.govtech-kz.com/admin"
echo "Logs: ssh ${SSH_TARGET} 'tail -f ~/talap/talap.log'"
