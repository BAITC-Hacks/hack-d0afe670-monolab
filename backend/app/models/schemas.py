from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class MatchRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    defect_type: Optional[str] = Field(default="pothole", max_length=64)


class SupplierInfo(BaseModel):
    name: str
    bin: str


class MatchResponse(BaseModel):
    match_found: bool
    street_name: Optional[str] = None
    address_display: Optional[str] = None
    contract_id: Optional[str] = None
    trd_buy_id: Optional[str] = None
    contract_title: Optional[str] = None
    customer_name: Optional[str] = None
    supplier: Optional[SupplierInfo] = None
    warranty_active: Optional[bool] = None
    warranty_ends: Optional[str] = None
    days_remaining: Optional[int] = None
    completed_on: Optional[str] = None
    message: str


class HealthResponse(BaseModel):
    status: str
    database: bool
    goszakup: bool
    contracts_count: Optional[int] = None
    tenderai_contracts: Optional[int] = None
    data_source: str = "tenderai"
    goszakup_live_enabled: bool = False


class EOtinishLinks(BaseModel):
    web_url: str
    android_intent: str
    ios_app_store: str
    android_play_store: str


class GpsCoords(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class UserInfo(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    iin: Optional[str] = Field(default=None, max_length=12)
    phone: Optional[str] = Field(default=None, max_length=32)


class DefectInfo(BaseModel):
    address_description: str = Field(..., min_length=3, max_length=500)
    gps: GpsCoords
    defect_type: Optional[str] = Field(default="pothole", max_length=200)
    severity: Optional[str] = Field(default="high", max_length=32)
    photo_urls: list[str] = Field(default_factory=list)
    photo_base64: Optional[str] = Field(default=None, max_length=8_000_000)


class ContractInfo(BaseModel):
    contract_number: Optional[str] = Field(default=None, max_length=128)
    trd_buy_id: Optional[str] = Field(default=None, max_length=64)
    contract_date: Optional[str] = Field(default=None, max_length=32)
    customer_name: Optional[str] = Field(default=None, max_length=500)
    supplier_name: Optional[str] = Field(default=None, max_length=500)
    supplier_bin: Optional[str] = Field(default=None, max_length=20)
    warranty_ends: Optional[str] = Field(default=None, max_length=32)
    warranty_active: Optional[bool] = None


class ComplaintGenerateRequest(BaseModel):
    user_info: Optional[UserInfo] = None
    defect_info: DefectInfo
    contract_info: Optional[ContractInfo] = None
    complaint_mode: str = Field(
        default="warranty",
        description="warranty = claim vs contractor; general = akimat maintenance request",
    )


class WarrantyRoadSegment(BaseModel):
    id: str
    label: str
    city: str
    street: Optional[str] = None
    contract_count: int
    warranty_active: bool
    coordinates: list[list[float]]  # [[lat, lng], ...] polyline along road
    center_lat: float
    center_lng: float


class WarrantyMapMarkersResponse(BaseModel):
    markers: list[WarrantyRoadSegment]
    total_contracts: int
    markers_on_map: int
    cities: list[str] = ["Алматы", "Астана"]


class ComplaintGenerateResponse(BaseModel):
    subject: str = Field(..., max_length=100)
    target_department: str
    document_body: str
    pdf_base64: Optional[str] = None
    pdf_filename: Optional[str] = None
    llm_enhanced: bool = False
    e_otinish: Optional[EOtinishLinks] = None
