from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.db import get_db
from app.models.complaint_schemas import (
    CitizenComplaintSubmitResponse,
    CitizenComplaintTrackResponse,
    ComplaintEventPublic,
    ComplaintStatus,
)
from app.models.schemas import MatchRequest
from app.services.complaint_workflow import (
    create_complaint_from_report,
    get_complaint_by_reg,
    load_events,
    read_media_file,
)
from app.services.cv_detector import NO_DEFECT_MESSAGE, get_cv_detector
from app.services.cv_upload import read_validated_image
from app.services.geocoder import reverse_geocode
from app.services.matcher import MatcherService

logger = logging.getLogger(__name__)
router = APIRouter()

# Public-safe fields only — warranty/contractor data is specialist-only.
_CITIZEN_FORBIDDEN_KEYS = frozenset(
    {
        "contract_id",
        "contractor_name",
        "contractor_bin",
        "warranty_end",
        "customer_name",
        "trd_buy_id",
        "reporter_token",
        "generated_claim_subject",
        "generated_claim_body",
    }
)


def _assert_citizen_safe(payload: dict) -> None:
    for key in _CITIZEN_FORBIDDEN_KEYS:
        if key in payload:
            raise RuntimeError(f"Citizen response leaked forbidden field: {key}")


@router.post("/complaints", response_model=CitizenComplaintSubmitResponse)
async def submit_complaint(
    file: UploadFile = File(..., description="Road defect photo"),
    lat: float = Form(..., ge=-90, le=90),
    lng: float = Form(..., ge=-180, le=180),
    description: str = Form(default="", max_length=2000),
) -> CitizenComplaintSubmitResponse:
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

    if cv_result.message == NO_DEFECT_MESSAGE or not cv_result.primary_defect:
        raise HTTPException(status_code=400, detail="no_defect_detected")

    geo = await reverse_geocode(lat, lng)
    address = geo.display_name if geo else f"{lat:.6f}, {lng:.6f}"

    try:
        match_result = await MatcherService().match(
            MatchRequest(lat=lat, lng=lng, defect_type=cv_result.primary_defect)
        )
    except Exception as exc:
        logger.error("match in complaints submit failed: %s", exc, exc_info=True)
        match_result = None

    async with get_db() as session:
        complaint = await create_complaint_from_report(
            session,
            image_bytes=image_bytes,
            lat=lat,
            lng=lng,
            description=description,
            cv=cv_result,
            match=match_result,
            address=address,
        )

        response = CitizenComplaintSubmitResponse(
            service_request_id=complaint.service_request_id,
            status=ComplaintStatus(complaint.status),
            response_deadline=complaint.response_deadline,
            agency_responsible=complaint.agency_responsible or "",
        )
        _assert_citizen_safe(response.model_dump())
        return response


@router.get("/complaints/{reg_number}", response_model=CitizenComplaintTrackResponse)
async def track_complaint(reg_number: str) -> CitizenComplaintTrackResponse:
    async with get_db() as session:
        complaint = await get_complaint_by_reg(session, reg_number)
        events = await load_events(session, complaint.id)

        response = CitizenComplaintTrackResponse(
            service_request_id=complaint.service_request_id,
            status=ComplaintStatus(complaint.status),
            service_code=complaint.service_code,
            service_name=complaint.service_name,
            address=complaint.address,
            description=complaint.description,
            requested_datetime=complaint.requested_datetime,
            updated_datetime=complaint.updated_datetime,
            response_deadline=complaint.response_deadline,
            agency_responsible=complaint.agency_responsible or "",
            events=[
                ComplaintEventPublic(
                    from_status=e.from_status,
                    to_status=e.to_status,
                    actor=e.actor,
                    note=e.note,
                    created_at=e.created_at,
                )
                for e in events
            ],
        )
        _assert_citizen_safe(response.model_dump())
        return response


@router.get("/complaints/media/{complaint_id}")
async def complaint_media(complaint_id: int) -> Response:
    data = read_media_file(complaint_id)
    return Response(content=data, media_type="image/jpeg")
