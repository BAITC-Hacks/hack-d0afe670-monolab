from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from app.config import DEFAULT_WARRANTY_YEARS

_EXPLICIT_WARRANTY_RE = re.compile(
    r"гарант\w*(?:\s+срок\w*)?\s*[—:\-]?\s*(\d+)\s*год",
    flags=re.IGNORECASE,
)

ROAD_KEYWORDS: tuple[str, ...] = (
    "ремонт",
    "дорог",
    "покрытие",
    "асфальт",
    "ямочн",
    "тротуар",
    "автодорог",
    "проезж",
    "капитальн",
    "текущ",
    "улиц",
    "проспект",
)

ROAD_EXCLUDE: tuple[str, ...] = (
    "кондиционер",
    "компьютер",
    "принтер",
    "камер",
    "охран",
    "здани",
    "колледж",
    "сметн",
)


def is_road_contract_text(text: str) -> bool:
    low = (text or "").lower()
    if not any(k in low for k in ROAD_KEYWORDS):
        return False
    road_work = ("дорог", "асфальт", "тротуар", "покрытие", "ямочн", "проезж", "капитальн", "текущ")
    if any(x in low for x in ROAD_EXCLUDE):
        if not any(k in low for k in road_work):
            return False
    # Address-only mention of a street (охрана, сигнализация, уборка…) is not road repair.
    non_road_at_address = ("охран", "сигнализа", "уборк", "освещен", "видеонаблюд")
    if any(x in low for x in non_road_at_address):
        if not any(k in low for k in road_work):
            return False
    return True


def infer_warranty_years(*texts: Optional[str]) -> int:
    blob = " ".join(t for t in texts if t).lower()
    match = _EXPLICIT_WARRANTY_RE.search(blob)
    if match:
        years = int(match.group(1))
        if 1 <= years <= 15:
            return years
    if "капитальн" in blob:
        return 5
    if "ямочн" in blob or "текущ" in blob:
        return 2
    return DEFAULT_WARRANTY_YEARS


def parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    return None


def warranty_end_date(completion: date, years: int) -> date:
    return completion + timedelta(days=max(years, 0) * 365)
