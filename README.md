# Talap — AI-Powered Road Defect Reporting

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)
![YOLO26](https://img.shields.io/badge/YOLO26-Ultralytics-purple)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/status-MVP-yellow)

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

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Service status + contract count |
| `GET` | `/api/v1/match` | GPS → warranty contract match |
| `POST` | `/api/v1/cv/detect` | Photo → AI defect detection |
| `POST` | `/api/v1/report` | Photo + GPS → full flow (CV + match + 3-tier severity routing) |
| `POST` | `/api/v1/complaint/generate` | Generate complaint document (legal claim or general request) + PDF |
| `GET` | `/api/v1/map/markers` | Road warranty polylines (Almaty/Astana) |

---

## Model Training

**Dataset sources:**
- RDD2022 (Japan + India subset) — cracks, potholes
- Saha et al. 2022 (Mendeley) — rutting
- BITS Roboflow, deduped + hazard-only — manhole hazards

```bash
cd backend
pip install -r training/requirements.txt

# Prepare dataset
python training/prepare_dataset.py \
  --extra-dataset /path/to/datasets \
  --output training/dataset_v1

# Train YOLO26
python training/train.py \
  --data training/dataset_v1/data.yaml \
  --epochs 25 \
  --device mps

# Evaluate
python training/eval.py \
  --weights runs/detect/training/runs/single_stage/weights/best.pt \
  --data training/dataset_v1/data.yaml \
  --split val
```

See `backend/training/RESULTS_V1.md` for training details and `SUBMISSION.md` for validation approach.

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

**Note:** Create `.env` files from `.env.example` — real `.env` files are gitignored. Never commit API keys, VPS credentials, or S3 secrets.

---

## Deployment (Planned)

| Component | Platform |
|-----------|----------|
| Frontend | Vercel (static) |
| Backend + DB | Railway / Render |
| CV GPU inference | Modal |

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