from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response

from app.config import SPECIALIST_API_KEY
from app.db import get_db
from app.models.complaint_schemas import (
    ComplaintEventPublic,
    ComplaintStatus,
    ComplaintTier,
    SpecialistActionRequest,
    SpecialistActionResponse,
    SpecialistComplaintDetail,
    SpecialistComplaintSummary,
    SpecialistRejectRequest,
    WarrantyBlock,
)
from app.services.complaint_clusters import build_complaint_clusters, urgency_rank
from app.services.complaint_workflow import (
    approve_complaint,
    build_complaint_pdf_bytes,
    get_complaint_by_id,
    load_events,
    maybe_start_review,
    reject_complaint,
    resolve_complaint,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _summary_from_complaint(c, cluster) -> SpecialistComplaintSummary:
    reports = cluster.reports_at_location if cluster else 1
    active = cluster.active_reports_at_location if cluster else 1
    return SpecialistComplaintSummary(
        id=c.id,
        service_request_id=c.service_request_id,
        status=ComplaintStatus(c.status),
        tier=ComplaintTier(c.tier),
        service_code=c.service_code,
        service_name=c.service_name,
        address=c.address,
        lat=c.lat,
        long=c.long,
        requested_datetime=c.requested_datetime,
        updated_datetime=c.updated_datetime,
        cv_confidence=c.cv_confidence,
        reports_at_location=reports,
        active_reports_at_location=active,
        location_key=cluster.location_key if cluster else None,
        cluster_label=cluster.cluster_label if cluster else None,
        urgency_score=urgency_rank(reports, c.tier),
    )


def require_specialist_key(x_specialist_key: Optional[str] = Header(default=None)) -> None:
    # Demo-grade auth: shared secret header. Production would use SSO / RBAC.
    if not SPECIALIST_API_KEY:
        raise HTTPException(status_code=503, detail="Specialist API not configured")
    if not x_specialist_key or x_specialist_key != SPECIALIST_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing specialist key")


@router.get(
    "/specialist/complaints",
    response_model=list[SpecialistComplaintSummary],
    dependencies=[Depends(require_specialist_key)],
)
async def list_complaints(
    status: Optional[str] = Query(default=None),
    tier: Optional[str] = Query(default=None),
    min_reports: int = Query(default=1, ge=1, le=100),
    sort: str = Query(default="urgency", pattern="^(urgency|date)$"),
) -> list[SpecialistComplaintSummary]:
    from sqlalchemy import select

    from app.models.db_models import Complaint

    async with get_db() as session:
        stmt = select(Complaint)
        if status:
            stmt = stmt.where(Complaint.status == status)
        if tier:
            stmt = stmt.where(Complaint.tier == tier)
        rows = list((await session.execute(stmt)).scalars().all())
        clusters = build_complaint_clusters(rows)

        summaries = [
            _summary_from_complaint(c, clusters.get(c.id))
            for c in rows
            if clusters.get(c.id) is None
            or clusters[c.id].reports_at_location >= min_reports
        ]

        if sort == "date":
            summaries.sort(key=lambda s: s.requested_datetime, reverse=True)
        else:
            summaries.sort(
                key=lambda s: (s.urgency_score, s.reports_at_location, s.requested_datetime),
                reverse=True,
            )
        return summaries


@router.get(
    "/specialist/complaints/{complaint_id}",
    response_model=SpecialistComplaintDetail,
    dependencies=[Depends(require_specialist_key)],
)
async def get_complaint_detail(complaint_id: int) -> SpecialistComplaintDetail:
    from sqlalchemy import select

    from app.models.db_models import Complaint

    async with get_db() as session:
        complaint = await get_complaint_by_id(session, complaint_id)
        complaint = await maybe_start_review(session, complaint)
        events = await load_events(session, complaint.id)

        all_rows = list((await session.execute(select(Complaint))).scalars().all())
        cluster = build_complaint_clusters(all_rows).get(complaint.id)
        base = _summary_from_complaint(complaint, cluster)

        warranty = None
        if complaint.contractor_name and complaint.contract_id:
            warranty = WarrantyBlock(
                contract_id=complaint.contract_id,
                contractor_name=complaint.contractor_name,
                contractor_bin=complaint.contractor_bin,
                warranty_end=complaint.warranty_end,
                customer_name=complaint.customer_name,
                trd_buy_id=complaint.trd_buy_id,
            )

        related = list(cluster.related_service_request_ids) if cluster else []
        related = [rid for rid in related if rid != complaint.service_request_id]

        return SpecialistComplaintDetail(
            **base.model_dump(),
            description=complaint.description,
            media_url=complaint.media_url,
            cv_bbox=complaint.cv_bbox,
            agency_responsible=complaint.agency_responsible or "",
            response_deadline=complaint.response_deadline,
            warranty=warranty,
            generated_claim_subject=complaint.generated_claim_subject,
            generated_claim_body=complaint.generated_claim_body,
            related_service_request_ids=related,
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


@router.get(
    "/specialist/complaints/{complaint_id}/pdf",
    dependencies=[Depends(require_specialist_key)],
)
async def complaint_pdf(complaint_id: int) -> Response:
    async with get_db() as session:
        complaint = await get_complaint_by_id(session, complaint_id)
        pdf_bytes = build_complaint_pdf_bytes(complaint)
        filename = f"{complaint.service_request_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )


@router.post(
    "/specialist/complaints/{complaint_id}/approve",
    response_model=SpecialistActionResponse,
    dependencies=[Depends(require_specialist_key)],
)
async def approve(complaint_id: int, body: SpecialistActionRequest) -> SpecialistActionResponse:
    async with get_db() as session:
        complaint = await get_complaint_by_id(session, complaint_id)
        complaint = await approve_complaint(session, complaint, body.note)
        return SpecialistActionResponse(
            id=complaint.id,
            service_request_id=complaint.service_request_id,
            status=ComplaintStatus(complaint.status),
            message="Complaint approved and forwarded",
        )


@router.post(
    "/specialist/complaints/{complaint_id}/reject",
    response_model=SpecialistActionResponse,
    dependencies=[Depends(require_specialist_key)],
)
async def reject(complaint_id: int, body: SpecialistRejectRequest) -> SpecialistActionResponse:
    async with get_db() as session:
        complaint = await get_complaint_by_id(session, complaint_id)
        complaint = await reject_complaint(session, complaint, body.reason)
        return SpecialistActionResponse(
            id=complaint.id,
            service_request_id=complaint.service_request_id,
            status=ComplaintStatus(complaint.status),
            message="Complaint rejected",
        )


@router.post(
    "/specialist/complaints/{complaint_id}/resolve",
    response_model=SpecialistActionResponse,
    dependencies=[Depends(require_specialist_key)],
)
async def resolve(complaint_id: int, body: SpecialistActionRequest) -> SpecialistActionResponse:
    async with get_db() as session:
        complaint = await get_complaint_by_id(session, complaint_id)
        complaint = await resolve_complaint(session, complaint, body.note)
        return SpecialistActionResponse(
            id=complaint.id,
            service_request_id=complaint.service_request_id,
            status=ComplaintStatus(complaint.status),
            message="Complaint marked resolved",
        )
