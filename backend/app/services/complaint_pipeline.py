from __future__ import annotations

import re
from datetime import datetime, timezone

from app.models.schemas import (
    ComplaintGenerateRequest,
    ComplaintGenerateResponse,
    EOtinishLinks,
)
from app.services.complaint import generate_complaint
from app.services.complaint_llm import polish_complaint_with_llm
from app.services.e_otinish import e_otinish_links
from app.services.pdf_complaint import build_complaint_pdf, pdf_to_base64


def _pdf_filename(address: str) -> str:
    slug = re.sub(r"[^\w\-]+", "_", address[:40], flags=re.UNICODE).strip("_")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"talap_zayavlenie_{slug or 'defect'}_{stamp}.pdf"


async def build_complaint_package(body: ComplaintGenerateRequest) -> ComplaintGenerateResponse:
    draft = generate_complaint(body)

    subject = draft.subject
    target = draft.target_department
    document_body = draft.document_body
    llm_enhanced = False

    polished = await polish_complaint_with_llm(body, subject, target, document_body)
    if polished:
        subject = polished["subject"]
        target = polished["target_department"]
        document_body = polished["document_body"]
        llm_enhanced = True

    pdf_bytes = build_complaint_pdf(
        subject=subject,
        document_body=document_body,
        address=body.defect_info.address_description,
        lat=body.defect_info.gps.lat,
        lng=body.defect_info.gps.lng,
        photo_base64=body.defect_info.photo_base64,
    )

    links = e_otinish_links()
    return ComplaintGenerateResponse(
        subject=subject,
        target_department=target,
        document_body=document_body,
        pdf_base64=pdf_to_base64(pdf_bytes),
        pdf_filename=_pdf_filename(body.defect_info.address_description),
        llm_enhanced=llm_enhanced,
        e_otinish=EOtinishLinks(**links),
    )
