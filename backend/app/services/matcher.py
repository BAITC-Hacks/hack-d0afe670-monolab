from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

import math

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import GOSZAKUP_LIVE_ENRICH_ENABLED, MATCH_DATA_SOURCE
from app.db import DB_AVAILABLE, get_db
from app.models.db_models import RoadContract, StreetGeocache
from app.models.schemas import MatchRequest, MatchResponse, SupplierInfo
from app.services import goszakup
from app.services.geocoder import GeoLocation, reverse_geocode
from app.services.warranty import infer_warranty_years, is_road_contract_text, parse_date, warranty_end_date

logger = logging.getLogger(__name__)

DB_MATCH_LIMIT = 50
_PROXIMITY_KM = 0.45


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class _Candidate:
    contract_id: str
    trd_buy_id: Optional[str]
    title: str
    street_name: Optional[str]
    customer_name: Optional[str]
    supplier_name: Optional[str]
    supplier_bin: Optional[str]
    completed_on: date
    warranty_ends: date
    days_remaining: int
    street_hits: int
    city_hits: int
    expired: bool


def _ilike_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _count_hits(blob: str, terms: tuple[str, ...]) -> int:
    low = blob.lower()
    return sum(1 for t in terms if t and t in low)


def _no_match(message: str, geo: Optional[GeoLocation] = None) -> MatchResponse:
    return MatchResponse(
        match_found=False,
        street_name=geo.street if geo else None,
        address_display=geo.display_name if geo else None,
        message=message,
    )


def _term_filter(terms: tuple[str, ...], *columns):
    if not terms:
        return None
    clauses = []
    for term in terms:
        pattern = f"%{_ilike_escape(term)}%"
        clauses.append(or_(*[col.ilike(pattern, escape="\\") for col in columns]))
    return or_(*clauses)


async def _query_road_contracts(session: AsyncSession, geo: GeoLocation) -> list[_Candidate]:
    blob_cols = (
        RoadContract.title,
        RoadContract.description,
        RoadContract.street_hint,
        RoadContract.region,
        RoadContract.city,
        RoadContract.customer_name,
    )
    street_filter = _term_filter(geo.street_terms, *blob_cols)
    city_filter = _term_filter(geo.city_terms, *blob_cols)

    stmt = select(RoadContract)
    if MATCH_DATA_SOURCE == "tenderai":
        stmt = stmt.where(RoadContract.source == "tenderai")
    if street_filter is not None:
        stmt = stmt.where(street_filter)
    if city_filter is not None:
        stmt = stmt.where(city_filter)
    stmt = stmt.order_by(
        RoadContract.completion_date.desc().nullslast(),
        RoadContract.sign_date.desc().nullslast(),
    ).limit(DB_MATCH_LIMIT)

    rows = (await session.execute(stmt)).scalars().all()
    today = date.today()
    candidates: list[_Candidate] = []
    for row in rows:
        if not is_road_contract_text(f"{row.title or ''} {row.description or ''}"):
            continue
        completion = row.completion_date or row.sign_date
        if completion is None or completion > today:
            continue
        years = row.warranty_period_years or infer_warranty_years(row.title, row.description)
        ends = warranty_end_date(completion, years)
        remaining = (ends - today).days
        text_blob = " ".join(
            p for p in (row.title, row.description, row.street_hint, row.city, row.region) if p
        )
        street_hits = _count_hits(text_blob, geo.street_terms)
        city_hits = _count_hits(text_blob, geo.city_terms)
        if street_hits == 0:
            continue
        candidates.append(
            _Candidate(
                contract_id=row.id,
                trd_buy_id=row.trd_buy_id,
                title=row.title or "",
                street_name=row.street_hint or geo.street,
                customer_name=row.customer_name,
                supplier_name=row.supplier_name,
                supplier_bin=row.supplier_bin,
                completed_on=completion,
                warranty_ends=ends,
                days_remaining=remaining,
                street_hits=street_hits,
                city_hits=city_hits,
                expired=remaining < 0,
            )
        )
    return candidates


async def _query_by_map_proximity(
    session: AsyncSession,
    lat: float,
    lng: float,
    geo: GeoLocation,
    today: date,
) -> list[_Candidate]:
    """Match contracts whose cached road segment is near the GPS pin."""
    caches = (await session.execute(select(StreetGeocache))).scalars().all()
    if not caches:
        return []

    nearby_keys: list[str] = []
    for cache in caches:
        if not cache.query_key.startswith("road|"):
            continue
        if _haversine_km(lat, lng, cache.lat, cache.lng) > _PROXIMITY_KM:
            continue
        nearby_keys.append(cache.query_key)

    if not nearby_keys:
        return []

    candidates: list[_Candidate] = []
    for key in nearby_keys:
        parts = key.split("|", 2)
        if len(parts) < 3:
            continue
        city, street = parts[1], parts[2]
        stmt = select(RoadContract).where(
            RoadContract.source == "tenderai",
            or_(
                RoadContract.street_hint.ilike(f"%{street}%"),
                RoadContract.title.ilike(f"%{street}%"),
            ),
        )
        if city:
            stmt = stmt.where(
                or_(
                    RoadContract.city.ilike(f"%{city}%"),
                    RoadContract.title.ilike(f"%{city}%"),
                )
            )
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            if not is_road_contract_text(f"{row.title or ''} {row.description or ''}"):
                continue
            completion = row.completion_date or row.sign_date
            if completion is None or completion > today:
                continue
            years = row.warranty_period_years or infer_warranty_years(row.title, row.description)
            ends = warranty_end_date(completion, years)
            remaining = (ends - today).days
            text_blob = " ".join(
                p for p in (row.title, row.description, row.street_hint, row.city) if p
            )
            street_hits = max(_count_hits(text_blob, geo.street_terms), 1)
            city_hits = _count_hits(text_blob, geo.city_terms) or 1
            candidates.append(
                _Candidate(
                    contract_id=row.id,
                    trd_buy_id=row.trd_buy_id,
                    title=row.title or "",
                    street_name=row.street_hint or street or geo.street,
                    customer_name=row.customer_name,
                    supplier_name=row.supplier_name,
                    supplier_bin=row.supplier_bin,
                    completed_on=completion,
                    warranty_ends=ends,
                    days_remaining=remaining,
                    street_hits=street_hits,
                    city_hits=city_hits,
                    expired=remaining < 0,
                )
            )
    return candidates


async def _enrich_from_goszakup(candidate: _Candidate, today: date) -> _Candidate:
    # Live Goszakup is opt-in only (GOSZAKUP_LIVE_ENRICH_ENABLED=1).
    if not GOSZAKUP_LIVE_ENRICH_ENABLED:
        return candidate
    if candidate.supplier_name and candidate.supplier_bin:
        return candidate
    if not candidate.trd_buy_id:
        return candidate
    raw = await goszakup.fetch_contract_by_buy_id(candidate.trd_buy_id)
    if not raw:
        return candidate

    supplier_obj = raw.get("Supplier") if isinstance(raw.get("Supplier"), dict) else {}
    customer_obj = raw.get("Customer") if isinstance(raw.get("Customer"), dict) else {}
    name = str(supplier_obj.get("nameRu") or "").strip() or candidate.supplier_name
    bin_ = str(raw.get("supplierBiin") or "").strip() or candidate.supplier_bin
    customer = str(customer_obj.get("nameRu") or "").strip() or candidate.customer_name
    signed = parse_date(raw.get("signDate")) or candidate.completed_on
    title = str(raw.get("trdBuyNameRu") or candidate.title)
    years = infer_warranty_years(title)
    ends = warranty_end_date(signed, years)
    remaining = (ends - today).days
    return _Candidate(
        contract_id=str(raw.get("id") or candidate.contract_id),
        trd_buy_id=candidate.trd_buy_id,
        title=title,
        street_name=candidate.street_name,
        customer_name=customer,
        supplier_name=name,
        supplier_bin=bin_,
        completed_on=signed,
        warranty_ends=ends,
        days_remaining=remaining,
        street_hits=candidate.street_hits,
        city_hits=candidate.city_hits,
        expired=remaining < 0,
    )


def _to_response(best: _Candidate, geo: GeoLocation) -> MatchResponse:
    supplier = None
    if best.supplier_name or best.supplier_bin:
        supplier = SupplierInfo(
            name=(best.supplier_name or "—").strip() or "—",
            bin=(best.supplier_bin or "").strip(),
        )
    winner = (best.supplier_name or "").strip() or (supplier.bin if supplier else "") or "не указан"
    street_label = best.street_name or geo.street or geo.display_name
    if best.expired:
        warranty_msg = (
            f"Гарантия истекла {best.warranty_ends.isoformat()} "
            f"({abs(best.days_remaining)} дн. назад)."
        )
    else:
        warranty_msg = (
            f"Гарантия действует до {best.warranty_ends.isoformat()} "
            f"({best.days_remaining} дн.)."
        )
    return MatchResponse(
        match_found=True,
        street_name=street_label,
        address_display=geo.display_name,
        contract_id=best.contract_id,
        trd_buy_id=best.trd_buy_id,
        contract_title=best.title,
        customer_name=best.customer_name,
        supplier=supplier,
        warranty_active=not best.expired,
        warranty_ends=best.warranty_ends.isoformat(),
        days_remaining=best.days_remaining,
        completed_on=best.completed_on.isoformat(),
        message=f"Последний победитель по адресу {street_label}: {winner}. {warranty_msg}",
    )


class MatcherService:
    def __init__(self, session: Optional[AsyncSession] = None) -> None:
        self._session = session

    async def match(self, request: MatchRequest) -> MatchResponse:
        geo = await reverse_geocode(request.lat, request.lng)
        if geo is None:
            return _no_match(
                "Не удалось определить адрес по координатам. Поставьте точку на дорогу и повторите."
            )
        if not geo.street_terms:
            return _no_match(
                f"Адрес: «{geo.display_name}», но улица не определена — сопоставление невозможно.",
                geo,
            )

        if not DB_AVAILABLE:
            return _no_match(
                "База Talap не настроена. Укажите DATABASE_URL и запустите ingest.",
                geo,
            )

        today = date.today()
        try:
            if self._session is not None:
                candidates = await _query_road_contracts(self._session, geo)
            else:
                async with get_db() as session:
                    candidates = await _query_road_contracts(session, geo)
        except Exception:
            logger.exception("match query failed")
            raise

        if not candidates:
            if self._session is not None:
                candidates = await _query_by_map_proximity(
                    self._session, request.lat, request.lng, geo, today
                )
            else:
                async with get_db() as session:
                    candidates = await _query_by_map_proximity(
                        session, request.lat, request.lng, geo, today
                    )

        if not candidates:
            return _no_match(
                f"По адресу «{geo.street or geo.display_name}» договоров на ремонт дороги не найдено "
                "в базе TenderAI (Алматы / Астана).",
                geo,
            )

        # Prefer latest completion in same city, then strongest street match.
        best = max(candidates, key=lambda c: (c.city_hits, c.completed_on, c.street_hits))
        best = await _enrich_from_goszakup(best, today)
        return _to_response(best, geo)
