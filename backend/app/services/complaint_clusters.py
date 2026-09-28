from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

# Complaints within this radius are treated as the same road segment.
CLUSTER_RADIUS_KM = 0.12  # ~120 m

_STREET_RE = re.compile(
    r"(?:ул\.?|улица|проспект|пр-т|пр\.?|бульвар|б-р|"
    r"переулок|пер\.?|шоссе|мкр\.?|микрорайон)\s+"
    r"([А-Яа-яӘәҒғҚқҢңӨөҰұҮүІіЁёA-Za-z0-9\-\s]{2,40})",
    flags=re.IGNORECASE,
)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _street_hint(address: str) -> str | None:
    match = _STREET_RE.search(address or "")
    if match:
        return match.group(1).strip(" ,.")
    return None


@dataclass(frozen=True)
class ComplaintClusterInfo:
    location_key: str
    reports_at_location: int
    active_reports_at_location: int
    cluster_label: str
    related_service_request_ids: tuple[str, ...]


def _cluster_label(addresses: Iterable[str]) -> str:
    streets: list[str] = []
    for addr in addresses:
        hint = _street_hint(addr)
        if hint and hint not in streets:
            streets.append(hint)
    if streets:
        return f"ул. {streets[0]}"
    first = next(iter(addresses), "")
    if first:
        return first.split(",")[0][:60]
    return "Участок дороги"


def build_complaint_clusters(rows: list) -> dict[int, ComplaintClusterInfo]:
    """
    Group complaints by GPS proximity. Returns per-complaint cluster stats.
    `rows` are Complaint ORM objects with id, lat, long, address, status, service_request_id.
    """
    if not rows:
        return {}

    # Union-find clustering
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if _haversine_km(rows[i].lat, rows[i].long, rows[j].lat, rows[j].long) <= CLUSTER_RADIUS_KM:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for idx in range(len(rows)):
        root = find(idx)
        groups.setdefault(root, []).append(idx)

    result: dict[int, ComplaintClusterInfo] = {}
    for members in groups.values():
        cluster_rows = [rows[i] for i in members]
        active = [r for r in cluster_rows if r.status not in ("REJECTED", "RESOLVED")]
        addresses = [r.address for r in cluster_rows if r.address]
        label = _cluster_label(addresses)
        rep = cluster_rows[0]
        location_key = f"{round(rep.lat, 4)}:{round(rep.long, 4)}"
        ids = tuple(
            r.service_request_id
            for r in sorted(
                cluster_rows,
                key=lambda r: (r.requested_datetime is not None, r.requested_datetime, r.id),
                reverse=True,
            )
        )
        info = ComplaintClusterInfo(
            location_key=location_key,
            reports_at_location=len(cluster_rows),
            active_reports_at_location=len(active),
            cluster_label=label,
            related_service_request_ids=ids,
        )
        for r in cluster_rows:
            result[r.id] = info

    return result


def urgency_rank(reports: int, tier: str) -> int:
    """Higher = more urgent for inbox sorting."""
    score = reports * 10
    if tier == "HAZARD_FASTTRACK":
        score += 50
    elif tier == "WARRANTY_CLAIM":
        score += 20
    if reports >= 5:
        score += 30
    elif reports >= 2:
        score += 10
    return score
