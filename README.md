# Talap — AI-Powered Road Defect Reporting

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)
![YOLO26](https://img.shields.io/badge/YOLO26-Ultralytics-purple)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/status-MVP-yellow)
[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://monolab.govtech-kz.com)

**Civic-tech solution for Kazakhstan:** Photo + GPS → AI defect detection → severity routing → warranty contract matching (when applicable) → complaint submission.

Built for **GovTech Camp 2026** (main partner: inDrive).

---

## Problem

Citizens see road defects (potholes, open manholes, cracks) but don't know:
- Whether it's dangerous enough to need urgent action
- Who last repaired the road, and whether warranty still applies
- How to file a legal complaint, or which department even owns the problem

Filing through e-Otinish requires manually picking a department and, for warranty cases, contractor info and contract numbers buried in procurement records that ordinary citizens can't access.

## Solution

**Talap automates the entire flow — and works on any road, warranty or not:**

```mermaid
flowchart TD
    A[📷 Photo + GPS] --> B[AI defect detection<br/>YOLO26, 5 classes]
    B --> C{Hazard-level?<br/>open manhole /<br/>large pothole}
    C -->|Yes| D[🚨 HAZARD_FASTTRACK<br/>Urgent dispatch, any road]
    C -->|No| E{GPS → goszakup<br/>contract match}
    E -->|Active warranty found| F[⚖️ WARRANTY_CLAIM<br/>Legal complaint vs. contractor]
    E -->|No contract / expired| G[🏙️ GENERAL_MAINTENANCE_REQUEST<br/>Routed to responsible akimat dept.]
    D --> H[Submit via e-Otinish]
    F --> H
    G --> H
```

Most roads at any moment are **not** inside an active warranty window — so instead of going silent on those photos, Talap always produces a usable, correctly-routed complaint:

| Tier | Trigger | Outcome |
|------|---------|---------|
| 🚨 **HAZARD_FASTTRACK** | Open/damaged manhole, large pothole (>2% image area) | Urgent dispatch, regardless of warranty status |
| ⚖️ **WARRANTY_CLAIM** | Crack, rutting, small pothole — active warranty found | Legal claim naming contractor + contract number |
| 🏙️ **GENERAL_MAINTENANCE_REQUEST** | Crack, rutting, small pothole — no active warranty / no contract on record | Standard complaint routed to the correct akimat department |

This is the same shape as international civic-tech tools (FixMyStreet, iKomek) — with warranty enforcement layered on top as the differentiator when a contract match exists.

---

## User Experience

### Citizen Flow (4 Steps)

**Streamlined from 6 to 4 steps** — warranty info is hidden from citizens and only shown in the specialist dashboard:

1. **📷 Фото** — Take photo (direct camera or upload)
2. **🔍 Проверка** — AI analyzes defect (YOLO detection + severity classification)
3. **📍 Адрес** — Confirm GPS location on map (auto-geocoded address)
4. **📤 Подача** — Review and submit complaint

Citizens receive a tracking number (`TLP-2026-NNNNNN`) and can monitor status at `/track/:reg`.

### Admin Panel

**Specialist dashboard** at `/admin` (or `/specialist`) — secured with `X-Specialist-Key` header:

- **📥 Inbox with filters:**
  - Status (pending / in_review / approved / rejected / resolved)
  - Urgency (all / 2+ reports / 5+ reports at same location)
  - Date/urgency sorting
- **🗺️ Clustering:** Groups complaints within ~120m, shows related reports count
- **📄 PDF export:** One-click complaint document download
- **⚡ Real-time polling:** Auto-refreshes inbox every 4 seconds
- **⚖️ Warranty display:** Shows contractor + contract ID when available (hidden from citizen UI)
- **✅ Workflow:** Approve → Reject → Resolve with timestamps

---

## Architecture

```mermaid
flowchart LR
    subgraph Client
        F[React + Vite<br/>Yandex MapKit]
    end
    subgraph Backend[FastAPI Backend]
        CV[CV Service<br/>YOLO26 inference]
        MATCH[Contract Matcher<br/>GPS → goszakup]
        SEV[Severity Router<br/>3-tier logic]
        DOC[Complaint Generator<br/>LLM + PDF]
    end
    subgraph Data
        DB[(PostgreSQL<br/>road_contracts<br/>goszakup sync)]
        GEO[Nominatim<br/>Reverse geocoding]
    end
    subgraph Infra
        MODAL[Modal GPU<br/>CV inference]
    end

    F -->|POST /report| Backend
    CV --> SEV
    MATCH --> SEV
    MATCH --> DB
    MATCH --> GEO
    SEV --> DOC
    DOC --> F
    CV -.optional remote inference.-> MODAL
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | React + Vite + Yandex MapKit |
| **Backend** | FastAPI + SQLAlchemy + PostgreSQL |
| **AI/CV** | YOLO26 (Ultralytics) — 5-class defect detection |
| **Geocoding** | Nominatim (OpenStreetMap) |
| **Data** | Kazakhstan public procurement ([ows.goszakup.gov.kz](https://ows.goszakup.gov.kz)) — completed road repair contracts, Almaty/Astana |

### 5-Class Defect Taxonomy

- `pothole` — potholes, surface failures
- `crack_longitudinal` — longitudinal/transverse cracks
- `crack_alligator` — alligator/fatigue cracking
- `sunken_manhole` — open or improperly closed manholes (hazard states only — normal closed covers are explicitly excluded from training)
- `rutting` — wheel-path depressions

---

## Project Structure

```
talap/
├── backend/             # FastAPI server
│   ├── app/            # API routes, services, models
│   ├── ingest/         # Contract data import scripts
│   ├── training/       # YOLO model training pipeline
│   └── deploy/         # Modal GPU deployment
├── frontend/           # React + Vite UI
├── docker-compose.yml  # Local Postgres setup
└── SUBMISSION.md       # Hackathon submission details
```

---

## Quick Start

### 1. Database

```bash
cd talap
docker compose up -d
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Copy example env and edit with your keys
cp .env.example .env

# Sync road repair contracts from goszakup (requires GOSZAKUP_TOKEN in .env)
python -m ingest.sync_road_contracts --days 90

# Start server
uvicorn app.main:app --reload --port 8001
```

### 3. Frontend

```bash
cd frontend
npm install

# Copy example env and add your Yandex Maps API key
cp .env.example .env

npm run dev
```

Open http://localhost:5173

---

## API Endpoints

### Public (Citizen)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Service status + contract count |
| `POST` | `/api/v1/cv/detect` | Photo → AI defect detection |
| `POST` | `/api/v1/complaints` | Submit complaint (photo + GPS) → registration number |
| `GET` | `/api/v1/complaints/{reg_number}` | Track complaint status (warranty fields hidden) |
| `GET` | `/api/v1/map/markers` | Warranty road markers (dots only, for map overlay) |

### Admin (Specialist Dashboard)

Requires `X-Specialist-Key: your-key-here` header (set via `SPECIALIST_API_KEY` in `backend/.env`).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/specialist/complaints` | Inbox with filters (`status`, `min_reports`, `sort=urgency\|date`) |
| `GET` | `/api/v1/specialist/complaints/{id}` | Full complaint detail (includes warranty, clustering, related IDs) |
| `GET` | `/api/v1/specialist/complaints/{id}/pdf` | Download complaint PDF |
| `PATCH` | `/api/v1/specialist/complaints/{id}` | Update status (approve / reject / resolve) |

### Internal (Legacy/Testing)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/match` | GPS → warranty contract match (direct query) |
| `POST` | `/api/v1/report` | Photo + GPS → full CV + match + routing (legacy endpoint) |
| `POST` | `/api/v1/complaint/generate` | Generate complaint doc (PDF) from CV + match results |

### Gateway Mode

Set `GOV_GATEWAY=internal` (default) or `GOV_GATEWAY=mock` in `backend/.env`:

- **`internal`:** Uses internal Postgres storage, no `simulated: true` flags
- **`mock`:** Simulates Smart Bridge gateway (for testing without real gov infra)

Production would replace the gateway layer in `app/services/gov_gateway.py` with a real API adapter to Kazakhstan's national service bus.

---

## Model Training

**Current model:** YOLO26s fine-tuned on 7,023 train / 731 val images (dataset_v1)  
**Performance:** val mAP50 **0.486** | manhole AP50 **0.846** (best class) | pothole AP50 **0.583**  
**Weights:** `backend/runs/detect/training/runs/single_stage/weights/best.pt` (19MB, epoch 21/25)  
**Confidence threshold:** 0.4 (production setting)

### Dataset Sources
- RDD2022 (Japan + India subset) — 4,124 potholes, 8,946 cracks
- Saha et al. 2022 (Mendeley) — 645 rutting instances
- BITS Roboflow, deduped + hazard-only — 206 manhole hazards

### Training Commands

```bash
cd backend
pip install -r training/requirements.txt

# Prepare dataset (merges sources, remaps classes, train/val/test split)
python training/prepare_dataset.py \
  --extra-dataset /path/to/RDD2022_japan_india:alligator_crack=crack_alligator,pothole=pothole \
  --extra-dataset /path/to/road_rutting_yolo:rutting=rutting \
  --extra-dataset /path/to/roboflow_manhole_dedup:manhole=sunken_manhole \
  --output training/dataset_v1

# Train YOLO26 (25 epochs, single-stage fine-tune, Apple MPS)
python training/train.py \
  --data training/dataset_v1/data.yaml \
  --epochs 25 \
  --device mps \
  --seed 42

# Evaluate on val split
python training/eval.py \
  --weights runs/detect/training/runs/single_stage/weights/best.pt \
  --data training/dataset_v1/data.yaml \
  --split val
```

### Results Summary (v1)

| Class | Precision | Recall | AP50 | Status |
|-------|-----------|--------|------|--------|
| **sunken_manhole** | 0.72 | 0.89 | **0.846** | ✅ Demo-ready (5/5 sanity at conf 0.4) |
| **pothole** | 0.59 | 0.69 | **0.583** | ✅ Demo-ready (7/7 sanity) |
| **crack_alligator** | 0.69 | 0.63 | **0.555** | ✅ Good |
| crack_longitudinal | 0.49 | 0.41 | 0.276 | ⚠️ Confuses with alligator |
| rutting | 0.65 | 0.21 | 0.172 | ⚠️ Weak (2/5 sanity) — needs more data |

**Known limitations:**  
- Training data is Japan/India road photos — no KZ-specific images yet; domain gap expected
- Phone-screen photos confuse the model (webcam of phone → manhole/pothole mislabeling)
- Rutting detection unreliable (21% recall) — avoid demoing on rutting defects

📄 **Full report:** [`backend/training/RESULTS_V1.md`](backend/training/RESULTS_V1.md)  
📋 **Validation logic:** [`SUBMISSION.md`](SUBMISSION.md)

---

## Environment Variables

### Backend (`backend/.env`)

```env
DATABASE_URL=postgresql://talap:talap@localhost:5433/talap
GOSZAKUP_TOKEN=your_token_here
YANDEX_MAPS_API_KEY=your_key_here
ROBOFLOW_API_KEY=your_key_here
CORS_ORIGINS=http://localhost:5173
```

### Frontend (`frontend/.env`)

```env
VITE_YANDEX_MAPS_API_KEY=your_key_here
```

### Admin Panel Access

Set `SPECIALIST_API_KEY` in `backend/.env` (any secret string). Access the admin panel at `/admin` or `/specialist` and enter this key at the login screen.

**Note:** Create `.env` files from `.env.example` — real `.env` files are gitignored. Never commit API keys, VPS credentials, or S3 secrets.

---

## Live Demo

🚀 **Citizen app:** [monolab.govtech-kz.com](https://monolab.govtech-kz.com)  
🔐 **Admin panel:** [monolab.govtech-kz.com/admin](https://monolab.govtech-kz.com/admin) — login with `SPECIALIST_API_KEY` from production `.env`

| Component | Platform | Status |
|-----------|----------|--------|
| Full Stack | govtech-kz.com:8016 | ✅ Live |
| CV Inference | VPS (CPU PyTorch) | ✅ Embedded in backend |
| Database | PostgreSQL (Docker) | ✅ 549 contracts indexed |
| Admin Dashboard | React (real-time polling) | ✅ Clustering + PDF export |

**GitHub:** [github.com/BAITC-Hacks/hack-d0afe670-monolab](https://github.com/BAITC-Hacks/hack-d0afe670-monolab)

---

## Hackathon Context

Built for **GovTech Camp 2026** (Case 3 — free case) as an MVP demonstrating:
- AI-powered civic engagement that works regardless of warranty status
- Warranty accountability for road maintenance where a contract match exists
- Integration with Kazakhstan's e-Gov infrastructure (e-Otinish)

**MVP scope:** Almaty + Astana coverage, 5 defect classes, 3-tier severity routing, goszakup road-repair contract index for warranty matching.

**Known limitations:** Training data is currently RDD2022 Japan+India subset (not all 6 countries) plus external manhole/rutting datasets — no Kazakhstan-specific photos yet. `sunken_manhole` has the least training data (~292 instances) and is the top priority for local field-photo collection. See `SUBMISSION.md` for full validation logic and known limitations.

**Future work:** Full RDD2022 dataset (6 countries), local KZ photos for domain adaptation, e-Otinish API integration (currently deep link + clipboard — no public API exists yet).

See `SUBMISSION.md` for detailed problem statement, data sources, and validation logic.

---

## License

MIT

---

## Team

Built by **MonoLab** for GovTech Camp 2026.