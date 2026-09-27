from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.config import NOMINATIM_TIMEOUT, NOMINATIM_URL, NOMINATIM_USER_AGENT

logger = logging.getLogger(__name__)

_STREET_TYPE = (
    r"улица|ул\.?|проспект|пр-т|пр\.?|бульвар|б-р|"
    r"переулок|пер\.?|шоссе|площадь|пл\.?|"
    r"микрорайон|мкр\.?|"
    r"даңғылы|даңғыл|көшесі|көше|алаңы|тұйық"
)
_STREET_PREFIX_RE = re.compile(rf"^(?:{_STREET_TYPE})\s+", flags=re.IGNORECASE)
_STREET_SUFFIX_RE = re.compile(rf"\s+(?:{_STREET_TYPE})$", flags=re.IGNORECASE)
_STREET_STOPWORDS = frozenset(
    {
        "проспект",
        "пр-т",
        "улица",
        "ул",
        "бульвар",
        "шоссе",
        "переулок",
        "микрорайон",
        "мкр",
        "площадь",
        "көшесі",
        "көше",
    }
)

CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "алматы": ("алматы", "almaty", "алма-ата"),
    "астана": ("астана", "нур-султан", "nur-sultan", "astana"),
    "шымкент": ("шымкент", "shymkent"),
    "актобе": ("актобе", "aktobe"),
    "караганда": ("караганда", "қарағанды", "karaganda"),
    "атырау": ("атырау", "atyrau"),
    "актау": ("актау", "мангистау", "aktau"),
    "павлодар": ("павлодар", "pavlodar"),
    "костанай": ("костанай", "қостанай", "kostanay"),
    "кызылорда": ("кызылорда", "қызылорда", "kyzylorda"),
    "тараз": ("тараз", "жамбыл", "taraz"),
    "туркестан": ("туркестан", "turkestan"),
}


@dataclass(frozen=True)
class GeoLocation:
    display_name: str
    street: Optional[str]
    city: Optional[str]
    district: Optional[str]
    street_terms: tuple[str, ...]
    city_terms: tuple[str, ...]


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def strip_street_prefix(name: str) -> str:
    cleaned = _STREET_PREFIX_RE.sub("", _normalize(name))
    cleaned = _STREET_SUFFIX_RE.sub("", cleaned).strip(" ,.")
    return cleaned or _normalize(name)


def _street_word_tokens(street: str) -> list[str]:
    """Significant words for fuzzy match (e.g. «серкебаева» from «пр. Ермека Серкебаева»)."""
    tokens: list[str] = []
    for raw in (_normalize(street), strip_street_prefix(street)):
        for word in re.split(r"[\s,.-]+", raw):
            w = word.strip()
            if len(w) < 4 or w in _STREET_STOPWORDS or w.isdigit():
                continue
            if w not in tokens:
                tokens.append(w)
    return tokens


def extract_search_terms(
    street: Optional[str],
    city: Optional[str],
    district: Optional[str] = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    street_terms: list[str] = []
    if street:
        for token in (_normalize(street), strip_street_prefix(street)):
            if token and len(token) >= 3 and token not in street_terms:
                street_terms.append(token)
        for word in _street_word_tokens(street):
            if word not in street_terms:
                street_terms.append(word)

    city_terms: list[str] = []
    if city:
        key = _normalize(city)
        for token in CITY_ALIASES.get(key, (key,)):
            if token and token not in city_terms:
                city_terms.append(token)
    if district:
        d = _normalize(district)
        core = re.sub(r"\s+район$", "", d).strip()
        for token in (d, core):
            if token and len(token) >= 4 and token not in city_terms:
                city_terms.append(token)

    return tuple(street_terms), tuple(city_terms)


def parse_nominatim(payload: dict[str, Any]) -> Optional[GeoLocation]:
    address = payload.get("address") if isinstance(payload.get("address"), dict) else {}
    street = (
        address.get("road")
        or address.get("pedestrian")
        or address.get("residential")
        or address.get("street")
    )
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
    )
    district = (
        address.get("suburb")
        or address.get("city_district")
        or address.get("borough")
        or address.get("district")
    )
    street = str(street).strip() if street else None
    city = str(city).strip() if city else None
    district = str(district).strip() if district else None

    display = str(payload.get("display_name") or "").strip()
    if not display:
        display = ", ".join(p for p in (street, district, city) if p)

    if not street and not city:
        return None

    street_terms, city_terms = extract_search_terms(street, city, district)
    return GeoLocation(
        display_name=display,
        street=street,
        city=city,
        district=district,
        street_terms=street_terms,
        city_terms=city_terms,
    )


_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_MIN_SEGMENT_DEG = 0.003


def _bbox_to_polyline(bbox: list[str]) -> tuple[tuple[float, float], ...]:
    """Nominatim bbox: [south, north, west, east]."""
    if len(bbox) != 4:
        return ()
    south, north, west, east = map(float, bbox)
    lng_span = abs(east - west)
    lat_span = abs(north - south)
    if lng_span >= lat_span:
        mid_lat = (south + north) / 2
        lng_a, lng_b = west, east
        if lng_b - lng_a < _MIN_SEGMENT_DEG:
            mid = (lng_a + lng_b) / 2
            lng_a, lng_b = mid - _MIN_SEGMENT_DEG / 2, mid + _MIN_SEGMENT_DEG / 2
        return ((mid_lat, lng_a), (mid_lat, lng_b))
    mid_lng = (west + east) / 2
    lat_a, lat_b = south, north
    if lat_b - lat_a < _MIN_SEGMENT_DEG:
        mid = (lat_a + lat_b) / 2
        lat_a, lat_b = mid - _MIN_SEGMENT_DEG / 2, mid + _MIN_SEGMENT_DEG / 2
    return ((lat_a, mid_lng), (lat_b, mid_lng))


async def forward_geocode_street(
    city: str, street: str
) -> Optional[tuple[float, float, tuple[tuple[float, float], ...]]]:
    """Return (lat, lng, polyline) for a street in a city."""
    query = f"{street}, {city}, Kazakhstan"
    params = {"q": query, "format": "json", "limit": 1, "addressdetails": 0}
    headers = {"User-Agent": NOMINATIM_USER_AGENT, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=NOMINATIM_TIMEOUT) as client:
            resp = await client.get(_SEARCH_URL, params=params, headers=headers)
            resp.raise_for_status()
            items = resp.json()
    except Exception as exc:
        logger.warning("forward geocode failed %r: %s", query[:80], exc)
        return None
    if not isinstance(items, list) or not items:
        return None
    item = items[0]
    try:
        lat = float(item["lat"])
        lng = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    bbox = item.get("boundingbox")
    polyline = _bbox_to_polyline(bbox) if isinstance(bbox, list) else ()
    if not polyline:
        polyline = ((lat, lng - _MIN_SEGMENT_DEG), (lat, lng + _MIN_SEGMENT_DEG))
    return lat, lng, polyline


async def reverse_geocode(lat: float, lng: float) -> Optional[GeoLocation]:
    params = {
        "lat": f"{lat:.7f}",
        "lon": f"{lng:.7f}",
        "format": "json",
        "addressdetails": "1",
        "zoom": "18",
        "accept-language": "ru",
    }
    headers = {"User-Agent": NOMINATIM_USER_AGENT, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=NOMINATIM_TIMEOUT) as client:
            resp = await client.get(NOMINATIM_URL, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.warning("geocode failed lat=%s lng=%s: %s", lat, lng, exc)
        return None
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    return parse_nominatim(payload)
