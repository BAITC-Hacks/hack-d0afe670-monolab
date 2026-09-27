from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

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
