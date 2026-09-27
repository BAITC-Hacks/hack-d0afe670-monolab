from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.cv_schemas import CVDetectionResponse
from app.services.cv_detector import get_cv_detector
from app.services.cv_upload import read_validated_image

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/cv/detect", response_model=CVDetectionResponse)
async def detect_defect(
    file: UploadFile = File(..., description="Road defect photo (JPEG or PNG, max 10 MB)"),
) -> CVDetectionResponse:
    detector = get_cv_detector()
    if not detector.is_ready:
        raise HTTPException(
            status_code=503,
            detail=detector.load_error or "CV model is not loaded.",
        )

    image_bytes = await read_validated_image(file)

    try:
        return await detector.detect(image_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("CV detection failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Defect detection failed.") from exc
