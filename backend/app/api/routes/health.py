from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from app.config import GOSZAKUP_LIVE_ENRICH_ENABLED, GOSZAKUP_TOKEN, MATCH_DATA_SOURCE
from app.db import DB_AVAILABLE, get_db
from app.models.db_models import RoadContract
from app.models.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health():
    count = None
    tenderai_count = None
    if DB_AVAILABLE:
        try:
            async with get_db() as session:
                count = int(
                    (await session.execute(select(func.count()).select_from(RoadContract))).scalar_one()
                )
                tenderai_count = int(
                    (
                        await session.execute(
                            select(func.count()).select_from(RoadContract).where(
                                RoadContract.source == "tenderai"
                            )
                        )
                    ).scalar_one()
                )
        except Exception:
            count = None
            tenderai_count = None
    return HealthResponse(
        status="ok",
        database=DB_AVAILABLE,
        goszakup=bool(GOSZAKUP_TOKEN),
        contracts_count=count,
        tenderai_contracts=tenderai_count,
        data_source=MATCH_DATA_SOURCE,
        goszakup_live_enabled=GOSZAKUP_LIVE_ENRICH_ENABLED,
    )
