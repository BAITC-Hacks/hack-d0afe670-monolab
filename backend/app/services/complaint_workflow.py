from __future__ import annotations

import base64
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.complaint_schemas import (
    ComplaintEventActor,
    ComplaintStatus,
    ComplaintTier,
)
from app.models.cv_schemas import CVDetectionResponse, SeverityTier
from app.models.db_models import Complaint, ComplaintEvent
from app.models.schemas import (
    ComplaintGenerateRequest,
    ContractInfo,
    DefectInfo,
    GpsCoords,
    MatchResponse,
)
from app.services.complaint import generate_complaint
from app.services.gov_gateway import GatewayReceipt, get_gov_gateway
from app.services.pdf_complaint import build_complaint_pdf

logger = logging.getLogger(__name__)

_UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "complaints"

DEFECT_SERVICE_NAMES: dict[str, str] = {
    "pothole": "Глубокая выбоина (яма)",
    "crack_longitudinal": "Продольная трещина покрытия",
    "crack_alligator": "Сетка трещин (усталостное разрушение)",
    "sunken_manhole": "Повреждённый / открытый люк",
    "rutting": "Колейность проезжей части",
}

VALID_TRANSITIONS: dict[ComplaintStatus, set[ComplaintStatus]] = {
    ComplaintStatus.SUBMITTED: {ComplaintStatus.REGISTERED},
    ComplaintStatus.REGISTERED: {
        ComplaintStatus.IN_REVIEW,
        ComplaintStatus.FORWARDED,
        ComplaintStatus.REJECTED,
    },
    ComplaintStatus.IN_REVIEW: {
        ComplaintStatus.FORWARDED,
        ComplaintStatus.REJECTED,
    },
    ComplaintStatus.FORWARDED: {ComplaintStatus.RESOLVED},
    ComplaintStatus.RESOLVED: set(),
    ComplaintStatus.REJECTED: set(),
}


def decide_tier(
    cv_severity: Optional[SeverityTier],
    match: Optional[MatchResponse],
) -> ComplaintTier:
    if cv_severity == SeverityTier.HAZARD_FASTTRACK:
        return ComplaintTier.HAZARD_FASTTRACK
    if match and match.match_found and match.warranty_active:
        return ComplaintTier.WARRANTY_CLAIM
    return ComplaintTier.GENERAL_MAINTENANCE_REQUEST


def assert_transition(current: ComplaintStatus, new: ComplaintStatus) -> None:
    allowed = VALID_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid status transition {current.value} → {new.value}",
        )


async def _next_service_request_id(session: AsyncSession) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"TLP-{year}-"
    result = await session.execute(
        select(func.max(Complaint.service_request_id)).where(
            Complaint.service_request_id.like(f"{prefix}%")
        )
    )
    last = result.scalar_one_or_none()
    seq = 1
    if last:
        try:
            seq = int(last.split("-")[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:06d}"


def _primary_detection(cv: CVDetectionResponse) -> tuple[Optional[str], Optional[float], Optional[list[float]]]:
    if not cv.detections:
        return None, None, None
    primary = cv.primary_defect or cv.detections[0].defect_class
    det = next((d for d in cv.detections if d.defect_class == primary), cv.detections[0])
    return det.defect_class, det.confidence, det.bbox


def _default_description(service_code: str, address: str) -> str:
    label = DEFECT_SERVICE_NAMES.get(service_code, service_code)
    return f"Зафиксирован дефект: {label}. Адрес: {address}."


def _save_photo(image_bytes: bytes, complaint_id: int) -> str:
    _UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    path = _UPLOAD_ROOT / f"{complaint_id}.jpg"
    path.write_bytes(image_bytes)
    return f"/api/v1/complaints/media/{complaint_id}"


async def _log_event(
    session: AsyncSession,
    complaint: Complaint,
    *,
    from_status: Optional[ComplaintStatus],
    to_status: ComplaintStatus,
    actor: ComplaintEventActor,
    note: Optional[str] = None,
) -> None:
    session.add(
        ComplaintEvent(
            complaint_id=complaint.id,
            from_status=from_status.value if from_status else None,
            to_status=to_status.value,
            actor=actor.value,
            note=note,
        )
    )


async def create_complaint_from_report(
    session: AsyncSession,
    *,
    image_bytes: bytes,
    lat: float,
    lng: float,
    description: Optional[str],
    cv: CVDetectionResponse,
    match: Optional[MatchResponse],
    address: str,
) -> Complaint:
    service_code, confidence, bbox = _primary_detection(cv)
    if not service_code:
        raise HTTPException(status_code=400, detail="no_defect_detected")

    tier = decide_tier(cv.severity_tier, match)
    service_name = DEFECT_SERVICE_NAMES.get(service_code, service_code)
    text = (description or "").strip() or _default_description(service_code, address)
    reg_id = await _next_service_request_id(session)
    now = datetime.now(timezone.utc)

    complaint = Complaint(
        service_request_id=reg_id,
        status=ComplaintStatus.SUBMITTED.value,
        service_code=service_code,
        service_name=service_name,
        lat=lat,
        long=lng,
        address=address,
        description=text,
        requested_datetime=now,
        updated_datetime=now,
        tier=tier.value,
        cv_confidence=confidence,
        cv_bbox=bbox,
        reporter_token=secrets.token_urlsafe(24),
        contract_id=match.contract_id if match and match.match_found else None,
        contractor_name=match.supplier.name if match and match.supplier else None,
        contractor_bin=match.supplier.bin if match and match.supplier else None,
        warranty_end=match.warranty_ends if match and match.match_found else None,
        customer_name=match.customer_name if match and match.match_found else None,
        trd_buy_id=match.trd_buy_id if match and match.match_found else None,
    )
    session.add(complaint)
    await session.flush()

    complaint.media_url = _save_photo(image_bytes, complaint.id)

    await _log_event(
        session,
        complaint,
        from_status=None,
        to_status=ComplaintStatus.SUBMITTED,
        actor=ComplaintEventActor.CITIZEN,
        note="Citizen submitted complaint",
    )

    gateway = get_gov_gateway()
    receipt: GatewayReceipt = await gateway.submit(
        service_request_id=reg_id,
        tier=tier,
        service_code=service_code,
        address=address,
        description=text,
    )

    complaint.status = ComplaintStatus.REGISTERED.value
    complaint.agency_responsible = receipt.agency_responsible
    complaint.response_deadline = receipt.response_deadline
    complaint.updated_datetime = datetime.now(timezone.utc)

    await _log_event(
        session,
        complaint,
        from_status=ComplaintStatus.SUBMITTED,
        to_status=ComplaintStatus.REGISTERED,
        actor=ComplaintEventActor.SYSTEM,
        note="Заявка зарегистрирована",
    )

    await session.flush()
    return complaint


async def get_complaint_by_reg(session: AsyncSession, reg_number: str) -> Complaint:
    result = await session.execute(
        select(Complaint).where(Complaint.service_request_id == reg_number)
    )
    complaint = result.scalar_one_or_none()
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return complaint


async def get_complaint_by_id(session: AsyncSession, complaint_id: int) -> Complaint:
    result = await session.execute(select(Complaint).where(Complaint.id == complaint_id))
    complaint = result.scalar_one_or_none()
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return complaint


async def load_events(session: AsyncSession, complaint_id: int) -> list[ComplaintEvent]:
    result = await session.execute(
        select(ComplaintEvent)
        .where(ComplaintEvent.complaint_id == complaint_id)
        .order_by(ComplaintEvent.created_at.asc())
    )
    return list(result.scalars().all())


async def maybe_start_review(session: AsyncSession, complaint: Complaint) -> Complaint:
    if complaint.status == ComplaintStatus.REGISTERED.value:
        assert_transition(ComplaintStatus.REGISTERED, ComplaintStatus.IN_REVIEW)
        await _log_event(
            session,
            complaint,
            from_status=ComplaintStatus.REGISTERED,
            to_status=ComplaintStatus.IN_REVIEW,
            actor=ComplaintEventActor.SPECIALIST,
            note="Specialist opened complaint for review",
        )
        complaint.status = ComplaintStatus.IN_REVIEW.value
        complaint.updated_datetime = datetime.now(timezone.utc)
        await session.flush()
    return complaint


def _build_claim_request(complaint: Complaint) -> ComplaintGenerateRequest:
    severity = "critical" if complaint.tier == ComplaintTier.HAZARD_FASTTRACK.value else "high"
    defect_type = complaint.service_code
    body = ComplaintGenerateRequest(
        complaint_mode="warranty" if complaint.tier == ComplaintTier.WARRANTY_CLAIM.value else "general",
        defect_info=DefectInfo(
            address_description=complaint.address,
            gps=GpsCoords(lat=complaint.lat, lng=complaint.long),
            defect_type=defect_type,
            severity=severity,
            photo_urls=[complaint.media_url] if complaint.media_url else [],
        ),
        contract_info=(
            ContractInfo(
                contract_number=complaint.trd_buy_id or complaint.contract_id,
                trd_buy_id=complaint.trd_buy_id,
                customer_name=complaint.customer_name,
                supplier_name=complaint.contractor_name,
                supplier_bin=complaint.contractor_bin,
                warranty_ends=complaint.warranty_end,
                warranty_active=True,
            )
            if complaint.contractor_name and complaint.contract_id
            else None
        ),
    )
    return body


def build_complaint_pdf_bytes(complaint: Complaint) -> bytes:
    """Build PDF for specialist view (uses saved claim text or generates draft)."""
    if complaint.generated_claim_subject and complaint.generated_claim_body:
        subject = complaint.generated_claim_subject
        document_body = complaint.generated_claim_body
    else:
        draft = generate_complaint(_build_claim_request(complaint))
        subject = draft.subject
        document_body = draft.document_body

    photo_b64: Optional[str] = None
    try:
        raw = read_media_file(complaint.id)
        photo_b64 = base64.b64encode(raw).decode("ascii")
    except HTTPException:
        pass

    return build_complaint_pdf(
        subject=subject,
        document_body=document_body,
        address=complaint.address,
        lat=complaint.lat,
        lng=complaint.long,
        photo_base64=photo_b64,
    )


async def approve_complaint(
    session: AsyncSession,
    complaint: Complaint,
    note: Optional[str],
) -> Complaint:
    current = ComplaintStatus(complaint.status)
    if current == ComplaintStatus.REGISTERED:
        await maybe_start_review(session, complaint)
        current = ComplaintStatus.IN_REVIEW

    assert_transition(current, ComplaintStatus.FORWARDED)

    draft = generate_complaint(_build_claim_request(complaint))
    complaint.generated_claim_subject = draft.subject
    complaint.generated_claim_body = draft.document_body

    forward_note = note or (
        "Forwarded to contractor under warranty"
        if complaint.tier == ComplaintTier.WARRANTY_CLAIM.value
        else "Forwarded to responsible department"
    )

    await _log_event(
        session,
        complaint,
        from_status=current,
        to_status=ComplaintStatus.FORWARDED,
        actor=ComplaintEventActor.SPECIALIST,
        note=forward_note,
    )
    complaint.status = ComplaintStatus.FORWARDED.value
    complaint.updated_datetime = datetime.now(timezone.utc)
    await session.flush()
    return complaint


async def reject_complaint(
    session: AsyncSession,
    complaint: Complaint,
    reason: str,
) -> Complaint:
    current = ComplaintStatus(complaint.status)
    if current == ComplaintStatus.REGISTERED:
        await maybe_start_review(session, complaint)
        current = ComplaintStatus.IN_REVIEW

    assert_transition(current, ComplaintStatus.REJECTED)
    await _log_event(
        session,
        complaint,
        from_status=current,
        to_status=ComplaintStatus.REJECTED,
        actor=ComplaintEventActor.SPECIALIST,
        note=reason,
    )
    complaint.status = ComplaintStatus.REJECTED.value
    complaint.updated_datetime = datetime.now(timezone.utc)
    await session.flush()
    return complaint


async def resolve_complaint(
    session: AsyncSession,
    complaint: Complaint,
    note: Optional[str],
) -> Complaint:
    current = ComplaintStatus(complaint.status)
    assert_transition(current, ComplaintStatus.RESOLVED)
    await _log_event(
        session,
        complaint,
        from_status=current,
        to_status=ComplaintStatus.RESOLVED,
        actor=ComplaintEventActor.SPECIALIST,
        note=note or "Marked resolved",
    )
    complaint.status = ComplaintStatus.RESOLVED.value
    complaint.updated_datetime = datetime.now(timezone.utc)
    await session.flush()
    return complaint


def read_media_file(complaint_id: int) -> bytes:
    path = _UPLOAD_ROOT / f"{complaint_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    return path.read_bytes()
