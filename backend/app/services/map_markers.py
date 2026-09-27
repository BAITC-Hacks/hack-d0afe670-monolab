from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MATCH_DATA_SOURCE
from app.db import get_db
from app.models.db_models import RoadContract, StreetGeocache
from app.models.schemas import WarrantyMapMarkersResponse, WarrantyRoadSegment
from app.services.warranty import infer_warranty_years, is_road_contract_text, warranty_end_date
from app.services.geocoder import forward_geocode_street
from app.services.yandex_geocoder import polyline_from_json, polyline_to_json

logger = logging.getLogger(__name__)

_STREET_IN_TITLE = re.compile(
    r"(?:ул\.?|улица|улице|проспект|пр-т|пр\.?|бульвар|б-р|"
    r"переулок|пер\.?|шоссе|мкр\.?|микрорайон)\s+([А-Яа-яӘәҒғҚқҢңӨөҰұҮүІіЁёA-Za-z0-9\-\s]{2,50})",
    flags=re.IGNORECASE,
)

_ALMATY_CITY = re.compile(r"города?\s+алматы|г\.\s*алматы|,\s*алматы\b", re.IGNORECASE)
_ASTANA_CITY = re.compile(r"города?\s+астаны|г\.\s*астана|нур-?султан|астана\b", re.IGNORECASE)


def _norm(text: Optional[str]) -> str:
    return (text or "").strip().lower()


def _city_bucket(city: Optional[str], title: str, customer: Optional[str]) -> Optional[str]:
    """Return canonical city name Алматы / Астана or None."""
    blob = f"{city or ''} {title} {customer or ''}"
    c = _norm(city)

    if "алматинская обл" in c and not _ALMATY_CITY.search(blob):
        return None
    if c == "алматы" or _ALMATY_CITY.search(blob):
        return "Алматы"
    if "астан" in c or ("нур" in c and "султан" in c) or _ASTANA_CITY.search(blob):
        return "Астана"
    return None


def _infer_street(title: str, street_hint: Optional[str]) -> Optional[str]:
    if street_hint and street_hint.strip():
        return street_hint.strip()[:80]
    match = _STREET_IN_TITLE.search(title or "")
    if match:
        return match.group(1).strip(" ,.")
    return None


def _warranty_active(row: RoadContract, today: date) -> bool:
    completion = row.completion_date or row.sign_date
    if completion is None:
        return False
    years = row.warranty_period_years or infer_warranty_years(row.title, row.description)
    ends = warranty_end_date(completion, years)
    return (ends - today).days >= 0


async def _get_segment(
    session: AsyncSession,
    query_key: str,
    city: str,
    street: str,
) -> Optional[tuple[tuple[float, float], ...]]:
    cached = await session.get(StreetGeocache, query_key)
    if cached and cached.polyline_json:
        pl = polyline_from_json(cached.polyline_json)
        if pl:
            return pl
    if cached and cached.lat and cached.lng:
        lat, lng = cached.lat, cached.lng
        return ((lat, lng - 0.003), (lat, lng + 0.003))

    result = await forward_geocode_street(city, street)
    if result is None:
        return None

    lat, lng, polyline = result
    pl_json = polyline_to_json(polyline)
    stmt = insert(StreetGeocache).values(
        query_key=query_key,
        lat=lat,
        lng=lng,
        query_text=f"{city}, {street}"[:500],
        polyline_json=pl_json,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["query_key"],
        set_={
            "lat": lat,
            "lng": lng,
            "query_text": f"{city}, {street}"[:500],
            "polyline_json": pl_json,
        },
    )
    await session.execute(stmt)
    return polyline


async def build_warranty_markers(limit_geocode: int = 80) -> WarrantyMapMarkersResponse:
    today = date.today()
    geocoded = 0
    matched_rows = 0

    async with get_db() as session:
        stmt = select(RoadContract)
        if MATCH_DATA_SOURCE == "tenderai":
            stmt = stmt.where(RoadContract.source == "tenderai")
        stmt = stmt.where(
            or_(
                RoadContract.city.ilike("%алмат%"),
                RoadContract.city.ilike("%астан%"),
                RoadContract.title.ilike("%алмат%"),
                RoadContract.title.ilike("%астан%"),
                RoadContract.title.ilike("%нур%sултан%"),
            )
        )
        rows = (await session.execute(stmt)).scalars().all()

        buckets: dict[str, dict] = {}

        for row in rows:
            if not is_road_contract_text(f"{row.title or ''} {row.description or ''}"):
                continue

            city = _city_bucket(row.city, row.title or "", row.customer_name)
            if city is None:
                continue

            street = _infer_street(row.title or "", row.street_hint)
            if not street:
                continue

            matched_rows += 1
            key = f"road|{city}|{street}"
            active = _warranty_active(row, today)

            if key not in buckets:
                buckets[key] = {
                    "key": key,
                    "label": f"{street}, {city}",
                    "city": city,
                    "street": street,
                    "count": 0,
                    "active_count": 0,
                }
            buckets[key]["count"] += 1
            if active:
                buckets[key]["active_count"] += 1

        segments: list[WarrantyRoadSegment] = []
        for bucket in sorted(buckets.values(), key=lambda b: -b["count"]):
            query_key = bucket["key"]
            polyline: Optional[tuple[tuple[float, float], ...]] = None

            cached = await session.get(StreetGeocache, query_key)
            if cached and cached.polyline_json:
                polyline = polyline_from_json(cached.polyline_json)
            elif geocoded < limit_geocode:
                polyline = await _get_segment(
                    session, query_key, bucket["city"], bucket["street"]
                )
                geocoded += 1
                await asyncio.sleep(1.05)  # Nominatim rate limit

            if not polyline:
                continue

            segments.append(
                WarrantyRoadSegment(
                    id=query_key,
                    label=bucket["label"],
                    city=bucket["city"],
                    street=bucket["street"],
                    contract_count=bucket["count"],
                    warranty_active=bucket["active_count"] > 0,
                    coordinates=[[lat, lng] for lat, lng in polyline],
                )
            )

        await session.commit()

    return WarrantyMapMarkersResponse(
        markers=segments,
        total_contracts=matched_rows,
        markers_on_map=len(segments),
        cities=["Алматы", "Астана"],
    )
