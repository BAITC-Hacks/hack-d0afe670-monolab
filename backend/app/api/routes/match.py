from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import MatchRequest, MatchResponse
from app.services.matcher import MatcherService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/match", response_model=MatchResponse)
async def match_post(body: MatchRequest) -> MatchResponse:
    try:
        return await MatcherService().match(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("match failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Не удалось выполнить поиск.") from exc


@router.get("/match", response_model=MatchResponse)
async def match_get(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    defect_type: Optional[str] = Query(default="pothole"),
) -> MatchResponse:
    return await match_post(MatchRequest(lat=lat, lng=lng, defect_type=defect_type))
