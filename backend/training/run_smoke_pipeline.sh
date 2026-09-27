#!/usr/bin/env bash
# End-to-end smoke test: synthetic dataset → train → eval → local inference
# Run from talap/backend:
#   bash training/run_smoke_pipeline.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python3}"

echo "==> 1/4 Generate smoke dataset"
"$PYTHON" training/make_smoke_dataset.py --output training/dataset_smoke --per-class 8

echo "==> 2/4 Two-stage fine-tune (3 epochs total — smoke only)"
"$PYTHON" training/train.py \
  --data training/dataset_smoke/data.yaml \
  --epochs 3 \
  --batch 4 \
  --imgsz 320 \
  --device cpu

echo "==> 3/5 Baseline (pretrained, test split)"
"$PYTHON" training/train.py \
  --data training/dataset_smoke/data.yaml \
  --baseline-only \
  --imgsz 320 \
  --device cpu \
  --seed 42

echo "==> 4/5 Evaluate trained model on test split"
"$PYTHON" training/eval.py \
  --weights training/weights/best.pt \
  --data training/dataset_smoke/data.yaml \
  --split test \
  --imgsz 320 \
  --device cpu \
  --seed 42 \
  --compare-to training/eval_output/metrics_latest.json

echo "==> 5/5 Local inference smoke test"

"$PYTHON" scripts/test_cv_inference.py

echo "Done. Weights at training/weights/best.pt"
