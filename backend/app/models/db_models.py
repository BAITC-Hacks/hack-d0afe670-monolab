from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RoadContract(Base):
    """Signed goszakup road-repair contracts indexed for GPS → warranty lookup."""

    __tablename__ = "road_contracts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trd_buy_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_bin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplier_bin: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    street_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    sign_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    completion_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    warranty_period_years: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    contract_sum: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="goszakup", nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )


class StreetGeocache(Base):
    """Cached geocoded points for warranty map markers."""

    __tablename__ = "street_geocache"

    query_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    query_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    polyline_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    geocoded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )


class Complaint(Base):
    """Open311 GeoReport v2-shaped citizen complaint."""

    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_request_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    service_code: Mapped[str] = mapped_column(String(64), nullable=False)
    service_name: Mapped[str] = mapped_column(String(256), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    long: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    media_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    requested_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    response_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    agency_responsible: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    cv_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    cv_bbox: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reporter_token: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    contract_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contractor_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    contractor_bin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    warranty_end: Mapped[str | None] = mapped_column(String(32), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    trd_buy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generated_claim_subject: Mapped[str | None] = mapped_column(String(256), nullable=True)
    generated_claim_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    events: Mapped[list["ComplaintEvent"]] = relationship(
        back_populates="complaint",
        cascade="all, delete-orphan",
    )


class ComplaintEvent(Base):
    """Audit log for complaint status changes."""

    __tablename__ = "complaint_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    complaint_id: Mapped[int] = mapped_column(
        ForeignKey("complaints.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )

    complaint: Mapped[Complaint] = relationship(back_populates="events")
