from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ComplaintStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REGISTERED = "REGISTERED"
    IN_REVIEW = "IN_REVIEW"
    FORWARDED = "FORWARDED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class ComplaintTier(str, Enum):
    HAZARD_FASTTRACK = "HAZARD_FASTTRACK"
    WARRANTY_CLAIM = "WARRANTY_CLAIM"
    GENERAL_MAINTENANCE_REQUEST = "GENERAL_MAINTENANCE_REQUEST"


class ComplaintEventActor(str, Enum):
    CITIZEN = "citizen"
    SYSTEM = "system"
    SPECIALIST = "specialist"


class ComplaintEventPublic(BaseModel):
    from_status: Optional[str] = None
    to_status: str
    actor: str
    note: Optional[str] = None
    created_at: datetime


class CitizenComplaintSubmitResponse(BaseModel):
    service_request_id: str
    status: ComplaintStatus
    response_deadline: datetime
    agency_responsible: str


class CitizenComplaintTrackResponse(BaseModel):
    service_request_id: str
    status: ComplaintStatus
    service_code: str
    service_name: str
    address: str
    description: str
    requested_datetime: datetime
    updated_datetime: datetime
    response_deadline: Optional[datetime] = None
    agency_responsible: str
    events: List[ComplaintEventPublic]


class WarrantyBlock(BaseModel):
    contract_id: Optional[str] = None
    contractor_name: Optional[str] = None
    contractor_bin: Optional[str] = None
    warranty_end: Optional[str] = None
    customer_name: Optional[str] = None
    trd_buy_id: Optional[str] = None


class SpecialistComplaintSummary(BaseModel):
    id: int
    service_request_id: str
    status: ComplaintStatus
    tier: ComplaintTier
    service_code: str
    service_name: str
    address: str
    lat: float
    long: float
    requested_datetime: datetime
    updated_datetime: datetime
    cv_confidence: Optional[float] = None
    reports_at_location: int = 1
    active_reports_at_location: int = 1
    location_key: Optional[str] = None
    cluster_label: Optional[str] = None
    urgency_score: int = 0


class SpecialistComplaintDetail(SpecialistComplaintSummary):
    description: str
    media_url: Optional[str] = None
    cv_bbox: Optional[Any] = None
    agency_responsible: str
    response_deadline: Optional[datetime] = None
    warranty: Optional[WarrantyBlock] = None
    generated_claim_subject: Optional[str] = None
    generated_claim_body: Optional[str] = None
    related_service_request_ids: List[str] = []
    events: List[ComplaintEventPublic]


class SpecialistActionRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


class SpecialistRejectRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=1000)


class SpecialistActionResponse(BaseModel):
    id: int
    service_request_id: str
    status: ComplaintStatus
    message: str
