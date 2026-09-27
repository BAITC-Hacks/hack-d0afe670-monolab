#!/usr/bin/env python3
"""
Sync signed goszakup contracts into Talap road_contracts table.

Usage (from talap/backend):
  python -m ingest.sync_road_contracts --days 90
  python -m ingest.sync_road_contracts --from 2024-01-01 --to 2026-12-31
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

# Polite defaults — do not hammer Goszakup (see README).
INGEST_WINDOW_DAYS = int(os.getenv("INGEST_WINDOW_DAYS", "14"))
INGEST_DELAY_SECONDS = float(os.getenv("INGEST_DELAY_SECONDS", "2.0"))
INGEST_PAGE_LIMIT = int(os.getenv("INGEST_PAGE_LIMIT", "100"))
INGEST_MAX_WINDOWS = int(os.getenv("INGEST_MAX_WINDOWS", "6"))

import httpx
from sqlalchemy.dialects.postgresql import insert

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.db import get_db, init_db
from app.models.db_models import RoadContract
from app.services import goszakup
from app.services.geocoder import CITY_ALIASES, strip_street_prefix
from app.services.warranty import infer_warranty_years, is_road_contract_text, parse_date

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_STREET_IN_TITLE = re.compile(
    r"(?:ул\.?|улица|проспект|пр-т|пр\.?|бульвар|б-р|"
    r"переулок|пер\.?|шоссе|мкр\.?|микрорайон)\s+([А-Яа-яӘәҒғҚқҢңӨөҰұҮүІіЁёA-Za-z0-9\-\s]{2,40})",
    flags=re.IGNORECASE,
)


def infer_city(title: str, customer: str) -> str | None:
    blob = f"{title} {customer}".lower()
    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            if alias in blob:
                return city.title() if city == "алматы" else city.capitalize()
    return None


def infer_street_hint(title: str) -> str | None:
    match = _STREET_IN_TITLE.search(title or "")
    if match:
        return match.group(1).strip(" ,.")
    for token in re.split(r"[\s,;]+", title or ""):
        core = strip_street_prefix(token)
        if len(core) >= 4 and core != token.lower():
            return core
    return None


def contract_row(raw: dict) -> dict | None:
    title = str(goszakup.pick(raw, "trdBuyNameRu", "trd_buy_name_ru") or "").strip()
    if not title or not is_road_contract_text(title):
        return None

    supplier = raw.get("Supplier") if isinstance(raw.get("Supplier"), dict) else {}
    customer = raw.get("Customer") if isinstance(raw.get("Customer"), dict) else {}
    sign = parse_date(goszakup.pick(raw, "signDate", "sign_date"))
    cid = str(goszakup.pick(raw, "id") or "").strip()
    if not cid:
        return None

    customer_name = str(customer.get("nameRu") or "").strip() or None
    city = infer_city(title, customer_name or "")
    street = infer_street_hint(title)
    years = infer_warranty_years(title)

    try:
        amount = int(float(goszakup.pick(raw, "contractSum", "contract_sum") or 0))
    except (TypeError, ValueError):
        amount = None

    return {
        "id": cid,
        "trd_buy_id": str(goszakup.pick(raw, "trdBuyId", "trd_buy_id") or "") or None,
        "title": title,
        "description": None,
        "customer_name": customer_name,
        "customer_bin": str(goszakup.pick(raw, "customerBin", "customer_bin") or "") or None,
        "supplier_name": str(supplier.get("nameRu") or "").strip() or None,
        "supplier_bin": str(goszakup.pick(raw, "supplierBiin", "supplier_biin") or "") or None,
        "region": city,
        "city": city,
        "street_hint": street,
        "sign_date": sign,
        "completion_date": sign,
        "warranty_period_years": years,
        "contract_sum": amount,
        "source": "goszakup",
    }


async def sync_range(start: date, end: date, *, max_windows: int | None = None) -> int:
    if not goszakup.GOSZAKUP_TOKEN:
        raise RuntimeError("GOSZAKUP_TOKEN is required for ingest")

    cap = max_windows if max_windows is not None else INGEST_MAX_WINDOWS
    await init_db()
    upserted = 0
    windows_done = 0
    cursor = start
    async with httpx.AsyncClient() as client:
        while cursor <= end:
            if windows_done >= cap:
                logger.warning(
                    "Stopped after %d API windows (INGEST_MAX_WINDOWS). "
                    "Run again later for more data.",
                    cap,
                )
                break
            window_end = min(cursor + timedelta(days=INGEST_WINDOW_DAYS - 1), end)
            logger.info(
                "Goszakup request %d/%d: %s .. %s (limit=%d)",
                windows_done + 1,
                cap,
                cursor,
                window_end,
                INGEST_PAGE_LIMIT,
            )
            batch = await goszakup.fetch_contracts_signed_between(
                client,
                sign_from=cursor.isoformat(),
                sign_to=window_end.isoformat(),
                limit=INGEST_PAGE_LIMIT,
            )
            windows_done += 1
            rows: list[dict] = []
            for item in batch:
                row = contract_row(item)
                if row:
                    rows.append(row)
            if rows:
                async with get_db() as session:
                    for row in rows:
                        stmt = insert(RoadContract).values(**row)
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["id"],
                            set_={k: v for k, v in row.items() if k != "id"},
                        )
                        await session.execute(stmt)
                upserted += len(rows)
                logger.info(
                    "window %s..%s: %d road contracts (total %d)",
                    cursor,
                    window_end,
                    len(rows),
                    upserted,
                )
            cursor = window_end + timedelta(days=1)
            if cursor <= end:
                await asyncio.sleep(INGEST_DELAY_SECONDS)
    return upserted


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync goszakup road contracts into Talap DB")
    p.add_argument("--days", type=int, default=21, help="Look back N days (default 21)")
    p.add_argument("--from", dest="date_from", type=str, default=None)
    p.add_argument("--to", dest="date_to", type=str, default=None)
    p.add_argument(
        "--max-windows",
        type=int,
        default=None,
        help=f"Max Goszakup API calls (default env INGEST_MAX_WINDOWS={INGEST_MAX_WINDOWS})",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Bypass GOSZAKUP_INGEST_ENABLED=0 guard (use only when necessary)",
    )
    return p.parse_args()


async def main() -> None:
    from app.config import GOSZAKUP_INGEST_ENABLED

    args = parse_args()
    if not GOSZAKUP_INGEST_ENABLED and not args.force:
        logger.error(
            "Goszakup ingest is disabled by default. "
            "Use TenderAI import: python -m ingest.import_from_tenderai\n"
            "To enable Goszakup sync: GOSZAKUP_INGEST_ENABLED=1 or pass --force"
        )
        sys.exit(1)

    end = date.today()
    if args.date_to:
        end = date.fromisoformat(args.date_to)
    if args.date_from:
        start = date.fromisoformat(args.date_from)
    else:
        start = end - timedelta(days=args.days)

    logger.info("Talap ingest %s → %s", start, end)
    n = await sync_range(start, end, max_windows=args.max_windows)
    logger.info("Done. Upserted %d road contracts.", n)


if __name__ == "__main__":
    asyncio.run(main())
