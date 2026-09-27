from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.models.schemas import ComplaintGenerateRequest, ComplaintGenerateResponse
from app.services.complaint_pipeline import build_complaint_package

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/complaint/generate", response_model=ComplaintGenerateResponse)
async def generate_complaint_document(body: ComplaintGenerateRequest) -> ComplaintGenerateResponse:
    try:
        return await build_complaint_package(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("complaint generate failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Не удалось сформировать заявление.") from exc
