# Talap CV — v1 Training Results

**Status:** **Complete — 25/25 epochs** (finished in Mac Terminal, 2026-09-28 01:55)  
**Date:** 2026-09-28  
**Weights:** `runs/detect/training/runs/single_stage/weights/best.pt` (best val checkpoint = **epoch 21**; epoch 25 did not beat it)  
**Dataset:** `training/dataset_v1` (7,023 train / 731 val images, 5 classes)

---

## Executive summary

First real multi-source model covering all five Talap defect classes. Full **25-epoch** run completed. Val mAP50 is **0.486** (best checkpoint at epoch 21; epochs 22–25 did not improve val mAP). **Demo-ready on potholes, alligator cracks, and manhole hazards**. Rutting improved but remains the weakest class (AP50 0.17, 2/5 sanity samples at conf 0.4).

**Production threshold decision: keep `CV_CONFIDENCE_THRESHOLD=0.4`.** At epoch 21, manholes hit 5/5 curated recall at 0.4 — no threshold change needed. Rutting gaps are a training/data issue, not a threshold issue.

---

## Training run

| Setting | Value |
|---------|-------|
| Model | YOLO26s (`yolo26s.pt`) |
| Mode | Single-stage fine-tune (`--no-freeze`) |
| Epochs planned | 25 |
| Epochs completed | **25** (best.pt from epoch 21) |
| Device | Apple MPS (M3 Pro) |
| Batch | 16 |
| Seed | 42 |
| Data | `training/dataset_v1/data.yaml` |

### Train split instance counts (dataset_v1)

| Class | Train instances |
|-------|-----------------|
| pothole | 4,124 |
| crack_longitudinal | 4,615 |
| crack_alligator | 4,331 |
| sunken_manhole | 206 |
| rutting | 645 |

### Sources merged

- RDD2022 Japan + India (HF subset) — pothole, cracks
- Saha et al. 2022 rutting (Mendeley) — `rutting`
- BITS Roboflow manhole (deduped, hazard-only) — `sunken_manhole` (`closed manhole` explicitly dropped)

### Progress vs earlier checkpoint (epoch 16 → 21)

| Metric | Epoch 16 | Epoch 21 | Δ |
|--------|----------|----------|---|
| val mAP50 | 0.436 | **0.486** | +0.050 |
| val mAP50-95 | 0.215 | **0.255** | +0.040 |
| sunken_manhole AP50 | 0.779 | **0.846** | +0.067 |
| rutting AP50 | 0.049 | **0.172** | +0.123 |

---

## Validation metrics (val split, conf=0.25 — eval default)

Evaluated with `training/eval.py --split val --allow-val`.

| Metric | Value |
|--------|-------|
| mAP50 | **0.486** |
| mAP50-95 | **0.255** |
| Precision | 0.628 |
| Recall | 0.566 |

### Per-class AP50 (val)

| Class | P | R | AP50 | Demo readiness |
|-------|---|---|------|----------------|
| pothole | 0.59 | 0.69 | **0.583** | Good |
| crack_longitudinal | 0.49 | 0.41 | **0.276** | Weak — confuses with alligator |
| crack_alligator | 0.69 | 0.63 | **0.555** | Good |
| sunken_manhole | 0.72 | 0.89 | **0.846** | Best class — demo-ready |
| rutting | 0.65 | 0.21 | **0.172** | Improved but still weak |

Confusion matrix: `training/eval_output/confusion_matrix.png`

---

## Demo sanity check (curated val samples, 5 per class)

Script: `training/sanity_check_model.py` — visual + severity-tier review, not a benchmark.

### At production conf **0.4** (what users get)

| Class | Recall (epoch 16) | Recall (epoch 21) |
|-------|-------------------|-------------------|
| pothole | 5/7 (71%) | **7/7 (100%)** |
| crack_longitudinal | 2/5 (40%) | 2/5 (40%) |
| crack_alligator | 4/6 (67%) | **5/6 (83%)** |
| sunken_manhole | 4/5 (80%) | **5/5 (100%)** |
| rutting | 0/5 (0%) | **2/5 (40%)** |

Flags at epoch 21: 6 MISS, **no DEMO_RISK on manholes**

Annotated outputs: `training/sanity_output/`

### Threshold decision (explicit)

**Keep `CV_CONFIDENCE_THRESHOLD=0.4`.** At epoch 21, manholes are 5/5 at production conf — the epoch-16 miss that motivated threshold investigation is resolved by more training, not by lowering conf. Rutting still misses 3/5 samples at 0.4; lowering conf would not reliably fix it and would increase `HAZARD_FASTTRACK` false positives.

---

## What works for demo

- **Open/improper manholes** → `HAZARD_FASTTRACK` (AP50 0.85, 5/5 sanity at conf 0.4)
- **Potholes** → detection + size-based hazard routing (7/7 sanity)
- **Alligator cracks** → `WARRANTY_CLAIM` routing

## What to avoid in demo

- **Rutting** — improved but unreliable (21% val recall, 2/5 sanity)
- **Longitudinal vs alligator** — frequent confusion
- **KZ asphalt/lighting** — no local training photos; domain gap expected

---

## Training curve note

Epochs 22–25 completed but val mAP50 peaked at epoch 21 (0.581 train-log / 0.486 eval). `best.pt` correctly kept the epoch-21 weights. `last.pt` is epoch 25 (optimizer stripped, 19 MB — inference-ready).

---

## v2 priorities

1. KZ field photos — especially rutting and local asphalt appearance
2. Rutting-specific augmentation or more Saha data
3. Held-out test eval (`eval.py --split test`)
4. Threshold calibration on real KZ photos before changing `CV_CONFIDENCE_THRESHOLD`
