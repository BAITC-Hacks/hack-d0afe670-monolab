from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.defect_report import DefectReportResponse
from app.models.schemas import MatchRequest
from app.services.cv_detector import NO_DEFECT_MESSAGE, get_cv_detector
from app.services.cv_upload import read_validated_image
from app.services.matcher import MatcherService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/report", response_model=DefectReportResponse)
async def report_defect(
    file: UploadFile = File(..., description="Road defect photo (JPEG or PNG, max 10 MB)"),
    lat: float = Form(..., ge=-90, le=90, description="WGS-84 latitude"),
    lng: float = Form(..., ge=-180, le=180, description="WGS-84 longitude"),
) -> DefectReportResponse:
    """Photo → YOLO defect detection → GPS warranty contract match."""
    detector = get_cv_detector()
    if not detector.is_ready:
        raise HTTPException(
            status_code=503,
            detail=detector.load_error or "CV model is not loaded.",
        )

    image_bytes = await read_validated_image(file)

    try:
        cv_result = await detector.detect(image_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("CV detection in report failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Defect detection failed.") from exc

    if cv_result.message == NO_DEFECT_MESSAGE or not cv_result.primary_defect:
        return DefectReportResponse(
            cv=cv_result,
            match=None,
            severity_tier=None,
            message=cv_result.message,
        )

    try:
        match_result = await MatcherService().match(
            MatchRequest(lat=lat, lng=lng, defect_type=cv_result.primary_defect)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("match in report failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Не удалось выполнить поиск.") from exc

    return DefectReportResponse(
        cv=cv_result,
        match=match_result,
        severity_tier=cv_result.severity_tier,
        message="defect_reported",
    )
