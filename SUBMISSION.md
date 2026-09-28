# Talap — Hackathon Submission Materials

**Product:** Talap — citizen road-defect reporting with warranty accountability  
**Stack:** React + FastAPI + YOLO26 + PostgreSQL + e-Otinish  
**Status:** MVP functional; CV model v1 training in progress (2026-09-27)

---

## 1. Problem Statement

Citizens in Kazakhstan see road defects (potholes, open manholes, cracks) but rarely know **who last repaired that road** or whether **warranty still applies**. Filing a complaint through e-Otinish requires knowing the contractor, contract number, and legal basis — information buried in procurement records.

**Talap solves:** photo + GPS → AI defect classification → match to warranty contract → auto-generated legal complaint → e-Otinish submission.

**Target users:** Residents of Almaty and Astana reporting road infrastructure defects under contractor warranty.

**Core pain:** Information asymmetry between citizens and road maintenance contractors; no simple link from a photo on the street to a enforceable warranty claim.

---

## 2. Data Sources

| Source | Role | Classes covered | License / access |
|--------|------|-----------------|------------------|
| **RDD2022** (Japan + India HF subset) | Crack + pothole training data | `pothole`, `crack_longitudinal`, `crack_alligator` | Open research dataset (CRDDC 2022); ~4,084 labeled images after empty-label filter |
| **Saha et al. 2022** (Mendeley `10.17632/v8mbnvx8pv.1`) | Rutting detection | `rutting` | CC BY 4.0; 949 images, 503 annotated |
| **BITS Roboflow** (`manhole_detection-wdc0v`, deduped) | Open/improperly-closed manhole hazards | `sunken_manhole` | CC BY 4.0; hazard-only mapping (closed manholes explicitly dropped) |
| **TenderAI import** | Warranty contract matching | N/A (procurement metadata) | Internal DB (~549 road contracts, Almaty/Astana) |
| **KZ field photos** | Domain adaptation (future) | All classes | **Not yet collected** — planned v2 |

**Deliberate v1 scope:** 2 of 6 RDD2022 countries (Japan + India), not the full 12 GB release. Sufficient for a genuine first model covering all 5 defect classes; remaining countries and local KZ photos are the natural v2 iteration.

**Warranty data:** `road_contracts` table imported from TenderAI (`source=tenderai`). Goszakup live API is disabled by default (`GOSZAKUP_INGEST_ENABLED=0`).

---

## 3. MVP Scope

### In scope (demo-ready)

| Feature | Implementation |
|---------|----------------|
| Map-based GPS selection | Yandex MapKit (Almaty default) |
| Warranty contract lookup | `GET/POST /api/v1/match` against TenderAI `road_contracts` |
| Photo → defect detection | `POST /api/v1/cv/detect` — YOLO26, 5-class taxonomy |
| Severity routing | `HAZARD_FASTTRACK` (open manhole, large pothole) vs `WARRANTY_CLAIM` (cracks, rutting, small potholes) |
| Complaint generation | PDF + e-Otinish deep link + clipboard |
| Map markers | Warranty polylines for Almaty/Astana |

### Out of scope (v1 / hackathon MVP)

- Full 6-country RDD2022 training set
- KZ-specific fine-tuning (no local labeled photos yet)
- On-device inference (backend/Modal only)
- Live Goszakup contract sync
- Transverse-crack as separate class (mapped to `crack_longitudinal`)
- Formal held-out test-set benchmark reporting for v1 (val used for quick check)

### 5-class defect taxonomy (fixed)

```
0: pothole
1: crack_longitudinal
2: crack_alligator
3: sunken_manhole
4: rutting
```

---

## 4. Validation Logic

### 4.1 Model validation (CV)

| Layer | Method | v1 approach |
|-------|--------|-------------|
| **Training data QA** | `prepare_dataset.py` audit tables, per-source balance report | Merge dry-runs + explicit-drop for manhole hazard-only |
| **De-augmentation** | `dedupe_roboflow_export.py` | Collapse Roboflow static aug copies (2,673 → 1,027) to prevent train/val leakage |
| **Metrics** | `training/eval.py` — mAP50, mAP50-95, per-class AP50 | v1 evaluated on **val split** (not held-out test) for speed; test reserved for v2 |
| **Demo sanity** | `training/sanity_check_model.py` | Per-class sample inference + severity-tier flags (not just mAP) |

**v1 training run:** 25 epochs, single-stage fine-tune, `dataset_v1` (7,023 train images, all 5 classes), YOLO26s on Apple MPS.

### 4.2 Severity / routing validation

Post-YOLO rules in `cv_detector.classify_severity()`:

| Tier | Trigger |
|------|---------|
| `HAZARD_FASTTRACK` | Any `sunken_manhole`, **or** `pothole` with bbox ≥ 2% of image area |
| `WARRANTY_CLAIM` | Cracks, rutting, small potholes |
| `null` | No detections above `CV_CONFIDENCE_THRESHOLD` (default 0.4) |

Sanity script flags: missed manholes, large potholes not fast-tracked, class mismatches — informs threshold tuning before live demo.

### 4.3 Product validation (end-to-end)

1. GPS on map → match returns contractor + warranty status
2. Photo upload → CV returns defect class + severity tier
3. Complaint PDF generates with matched contract details
4. e-Otinish link opens with pre-filled text

**Known limitations for demo:**

- `sunken_manhole` trained on only ~292 hazard instances — expect weakest live-camera performance
- Model trained on Japan/India/Roboflow imagery — KZ asphalt/lighting domain gap
- Frontend shows `severity_tier` but complaint payload still uses hardcoded severity (wiring gap)

**Threshold tuning decision (post-training):**

Production default: `CV_CONFIDENCE_THRESHOLD=0.4` (eval uses 0.25 for metrics).

If manhole detection is weak at 0.4, lowering to 0.25–0.3 raises recall but increases false positives. For `HAZARD_FASTTRACK` routing, false positives dispatch inspectors for nothing — real cost.

**Any threshold change for demo must be explicit in `RESULTS_V1.md` with rationale** (same transparency as class-mapping decisions). Don't silently tune to make demo numbers prettier.

---

## 5. How This Gets Better (v2 — not a v1 blocker)

1. **Remaining RDD2022 countries** — full 6-country merge when 12 GB download completes
2. **KZ field photos** — highest priority for `sunken_manhole` and local asphalt appearance
3. **Held-out test eval** — proper benchmark with `eval.py --split test`
4. **Threshold calibration** — tune `CV_CONFIDENCE_THRESHOLD` and `CV_POTHOLE_HAZARD_AREA_RATIO` on KZ samples
5. **Wire severity into complaint** — pass `severity_tier` through to PDF template

---

## Gateway simulation (Open311-shaped)

Talap stores citizen complaints in an Open311 GeoReport v2-inspired schema (`complaints` + `complaint_events` tables).

| Open311 field | Talap field |
|---------------|-------------|
| `service_request_id` | `service_request_id` (`TLP-YYYY-NNNNNN`) |
| `status` | `SUBMITTED` → `REGISTERED` → `IN_REVIEW` → `FORWARDED` → `RESOLVED` |
| `service_code` / `service_name` | YOLO defect class + Russian label |
| `lat` / `long` | GPS from citizen device |
| `address` / `description` | Reverse-geocoded address + editable text |
| `requested_datetime` | Submission timestamp |
| `agency_responsible` | Routed by tier/defect mapping (simulated) |

**What is real:** photo CV inference, GPS geocoding, warranty contract lookup (stored internally, not shown to citizens).

**What is simulated:** Smart Bridge registration, response deadline enforcement, inter-agency forwarding. All gateway responses include `"simulated": true`.

**Citizen vs specialist views:** citizens see registration number + status timeline only. Specialists see warranty block (contractor BIN, warranty end, contract #) when `WARRANTY_CLAIM` tier applies.

Replace `MockSmartBridgeGateway` (`GOV_GATEWAY=mock`) with a real adapter when API access is granted.

---

## Quick reference commands

```bash
# After v1 training finishes:
cd talap/backend
PYTHONPATH=. python training/sanity_check_model.py \\
  --weights runs/detect/training/runs/single_stage/weights/best.pt \\
  --data training/dataset_v1/data.yaml

PYTHONPATH=. python training/eval.py \\
  --weights runs/detect/training/runs/single_stage/weights/best.pt \\
  --data training/dataset_v1/data.yaml \\
  --split val --allow-val --device mps
```
