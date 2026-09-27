from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import YANDEX_MAPS_API_KEY

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://geocode-maps.yandex.ru/1.x/"
_last_call = 0.0
_MIN_INTERVAL = 0.12

_MIN_SEGMENT_DEG = 0.003  # ~300 m minimum segment length


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lng: float
    polyline: tuple[tuple[float, float], ...]  # (lat, lng) pairs


async def _throttle() -> None:
    global _last_call
    now = asyncio.get_event_loop().time()
    wait = _MIN_INTERVAL - (now - _last_call)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_call = asyncio.get_event_loop().time()


def _parse_pos(pos: str) -> Optional[tuple[float, float]]:
    parts = pos.split()
    if len(parts) != 2:
        return None
    lng, lat = float(parts[0]), float(parts[1])
    return lat, lng


def _envelope_to_polyline(
    lower_corner: str,
    upper_corner: str,
    center: tuple[float, float],
) -> tuple[tuple[float, float], ...]:
    """Build a road-like segment from Yandex boundedBy envelope."""
    lower = _parse_pos(lower_corner)
    upper = _parse_pos(upper_corner)
    if lower is None or upper is None:
        lat, lng = center
        return (
            (lat, lng - _MIN_SEGMENT_DEG),
            (lat, lng + _MIN_SEGMENT_DEG),
        )

    lat1, lng1 = lower
    lat2, lng2 = upper
    lng_span = abs(lng2 - lng1)
    lat_span = abs(lat2 - lat1)

    if lng_span >= lat_span:
        mid_lat = (lat1 + lat2) / 2
        lng_a, lng_b = min(lng1, lng2), max(lng1, lng2)
        if lng_b - lng_a < _MIN_SEGMENT_DEG:
            mid_lng = (lng_a + lng_b) / 2
            lng_a, lng_b = mid_lng - _MIN_SEGMENT_DEG / 2, mid_lng + _MIN_SEGMENT_DEG / 2
        return ((mid_lat, lng_a), (mid_lat, lng_b))

    mid_lng = (lng1 + lng2) / 2
    lat_a, lat_b = min(lat1, lat2), max(lat1, lat2)
    if lat_b - lat_a < _MIN_SEGMENT_DEG:
        mid_lat = (lat_a + lat_b) / 2
        lat_a, lat_b = mid_lat - _MIN_SEGMENT_DEG / 2, mid_lat + _MIN_SEGMENT_DEG / 2
    return ((lat_a, mid_lng), (lat_b, mid_lng))


async def geocode_street_segment(city: str, street: str) -> Optional[GeocodeResult]:
    """Geocode a street and return center point + polyline along the road axis."""
    if not YANDEX_MAPS_API_KEY:
        logger.warning("YANDEX_MAPS_API_KEY not set — cannot geocode")
        return None

    query = f"Казахстан, {city}, {street}"
    await _throttle()
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                _GEOCODE_URL,
                params={
                    "apikey": YANDEX_MAPS_API_KEY,
                    "geocode": query,
                    "format": "json",
                    "lang": "ru_RU",
                    "results": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("yandex geocode failed for %r: %s", query[:80], exc)
        return None

    members = (
        data.get("response", {})
        .get("GeoObjectCollection", {})
        .get("featureMember", [])
    )
    if not members:
        return None

    geo = members[0].get("GeoObject", {})
    center = _parse_pos(geo.get("Point", {}).get("pos", ""))
    if center is None:
        return None

    envelope = geo.get("boundedBy", {}).get("Envelope", {})
    polyline = _envelope_to_polyline(
        envelope.get("lowerCorner", ""),
        envelope.get("upperCorner", ""),
        center,
    )
    return GeocodeResult(lat=center[0], lng=center[1], polyline=polyline)


async def geocode_address(query: str) -> Optional[tuple[float, float]]:
    if not YANDEX_MAPS_API_KEY:
        return None
    await _throttle()
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                _GEOCODE_URL,
                params={
                    "apikey": YANDEX_MAPS_API_KEY,
                    "geocode": query,
                    "format": "json",
                    "lang": "ru_RU",
                    "results": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None
    members = (
        data.get("response", {})
        .get("GeoObjectCollection", {})
        .get("featureMember", [])
    )
    if not members:
        return None
    return _parse_pos(members[0].get("GeoObject", {}).get("Point", {}).get("pos", ""))


def polyline_to_json(polyline: tuple[tuple[float, float], ...]) -> str:
    return json.dumps([[lat, lng] for lat, lng in polyline])


def polyline_from_json(raw: str | None) -> tuple[tuple[float, float], ...]:
    if not raw:
        return ()
    try:
        data = json.loads(raw)
        return tuple((float(p[0]), float(p[1])) for p in data)
    except (json.JSONDecodeError, TypeError, IndexError, ValueError):
        return ()
