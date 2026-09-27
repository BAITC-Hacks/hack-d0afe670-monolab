from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/")
async def root():
    return {"service": "Talap", "docs": "/docs", "health": "/api/v1/health"}
