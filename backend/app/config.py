from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")
load_dotenv()

GOSZAKUP_TOKEN: str = os.getenv("GOSZAKUP_TOKEN", "").strip()
GOSZAKUP_GRAPHQL_URL: str = "https://ows.goszakup.gov.kz/v3/graphql"

# Match uses TenderAI-imported contracts only. Goszakup live API is opt-in.
MATCH_DATA_SOURCE: str = os.getenv("MATCH_DATA_SOURCE", "tenderai").strip().lower()
GOSZAKUP_LIVE_ENRICH_ENABLED: bool = os.getenv(
    "GOSZAKUP_LIVE_ENRICH_ENABLED", "0"
).strip().lower() in ("1", "true", "yes")
GOSZAKUP_INGEST_ENABLED: bool = os.getenv(
    "GOSZAKUP_INGEST_ENABLED", "0"
).strip().lower() in ("1", "true", "yes")

# Optional LLM polish (falls back to template if key missing)
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
COMPLAINT_LLM_ENABLED: bool = os.getenv(
    "COMPLAINT_LLM_ENABLED", "1" if OPENAI_API_KEY else "0"
).strip().lower() in ("1", "true", "yes")

E_OTINISH_WEB_URL: str = os.getenv(
    "E_OTINISH_WEB_URL", "https://eotinish.kz/ru/myApp"
).strip()
EGOV_ANDROID_PACKAGE: str = os.getenv("EGOV_ANDROID_PACKAGE", "kz.mobile.mgov").strip()
PDF_FONT_PATH: str = os.getenv("PDF_FONT_PATH", "").strip()

YANDEX_MAPS_API_KEY: str = os.getenv("YANDEX_MAPS_API_KEY", "").strip()

NOMINATIM_URL: str = os.getenv(
    "NOMINATIM_URL",
    "https://nominatim.openstreetmap.org/reverse",
)
NOMINATIM_USER_AGENT: str = os.getenv(
    "NOMINATIM_USER_AGENT",
    "Talap/1.0 (road warranty lookup; contact@talap.kz)",
)
NOMINATIM_TIMEOUT: float = float(os.getenv("NOMINATIM_TIMEOUT_SECONDS", "10"))

DEFAULT_WARRANTY_YEARS: int = int(os.getenv("ROAD_WARRANTY_YEARS_DEFAULT", "3"))
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

# ── Road defect CV (YOLO26) ───────────────────────────────────────────────────
CV_MODEL_PATH: str = os.getenv(
    "CV_MODEL_PATH",
    str(_ROOT / "training" / "weights" / "best.pt"),
)
CV_CONFIDENCE_THRESHOLD: float = float(os.getenv("CV_CONFIDENCE_THRESHOLD", "0.4"))
# Pothole bbox area / image area above this → HAZARD_FASTTRACK (tune with KZ photos).
CV_POTHOLE_HAZARD_AREA_RATIO: float = float(os.getenv("CV_POTHOLE_HAZARD_AREA_RATIO", "0.02"))
CV_MAX_IMAGE_BYTES: int = int(os.getenv("CV_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
CV_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/jpg", "image/png"})
USE_MODAL: bool = os.getenv("USE_MODAL", "").lower() in ("1", "true", "yes", "on")
MODAL_CV_APP_NAME: str = os.getenv("MODAL_CV_APP_NAME", "talap-cv")
MODAL_CV_FUNCTION_NAME: str = os.getenv("MODAL_CV_FUNCTION_NAME", "detect")
