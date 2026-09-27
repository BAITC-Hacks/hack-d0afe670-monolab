from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import complaint as complaint_routes
from app.api.routes import cv as cv_routes
from app.api.routes import health as health_routes
from app.api.routes import map as map_routes
from app.api.routes import match as match_routes
from app.api.routes import report as report_routes
from app.config import CORS_ORIGINS
from app.db import init_db
from app.services.cv_detector import get_cv_detector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        await get_cv_detector().initialize()
        if get_cv_detector().is_ready:
            logger.info("CV defect detector ready")
        else:
            logger.info(
                "CV detector not loaded (%s) — /cv/detect and /report return 503 until weights exist",
                get_cv_detector().load_error or "weights missing",
            )
    except Exception as exc:
        logger.warning("CV detector startup skipped: %s", exc)
    logger.info("Talap API started")
    yield
    logger.info("Talap API stopped")


app = FastAPI(
    title="Talap API",
    description="Кто последний ремонтировал дорогу и действует ли гарантия",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_routes.router, prefix="/api/v1", tags=["Health"])
app.include_router(match_routes.router, prefix="/api/v1", tags=["Match"])
app.include_router(cv_routes.router, prefix="/api/v1", tags=["Computer vision"])
app.include_router(report_routes.router, prefix="/api/v1", tags=["Report"])
app.include_router(complaint_routes.router, prefix="/api/v1", tags=["Complaint"])
app.include_router(map_routes.router, prefix="/api/v1", tags=["Map"])

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_ROOT.parent
_STATIC_DIR = Path(
    os.getenv("STATIC_DIR", str(_REPO_ROOT / "frontend" / "dist"))
).resolve()


def _mount_frontend() -> None:
    """Serve built React app from STATIC_DIR when present (production VPS deploy)."""
    if not _STATIC_DIR.is_dir() or not (_STATIC_DIR / "index.html").is_file():
        logger.info("Static frontend not found at %s — API-only mode", _STATIC_DIR)

        @app.get("/")
        async def root():
            return {"service": "Talap", "docs": "/docs", "health": "/api/v1/health"}

        return

    assets_dir = _STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    async def spa_index():
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path in ("docs", "openapi.json", "redoc"):
            raise HTTPException(status_code=404)
        candidate = _STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_STATIC_DIR / "index.html")

    logger.info("Serving static frontend from %s", _STATIC_DIR)


_mount_frontend()
