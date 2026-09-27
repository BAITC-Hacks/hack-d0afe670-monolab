from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.models.schemas import WarrantyMapMarkersResponse
from app.services.map_markers import build_warranty_markers

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/map/markers", response_model=WarrantyMapMarkersResponse)
async def warranty_map_markers() -> WarrantyMapMarkersResponse:
    try:
        return await build_warranty_markers()
    except Exception as exc:
        logger.error("map markers failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Не удалось загрузить маркеры карты.") from exc
