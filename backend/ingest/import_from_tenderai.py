#!/usr/bin/env python3
"""
One-way import: TenderAI Postgres → Talap road_contracts (read-only on source).

Uses winning supplier_participations + road-related tenders. No Goszakup API calls.

  cd talap/backend
  # TENDERAI_DATABASE_URL in .env or copied from tenderai-backend/.env
  python -m ingest.import_from_tenderai
  python -m ingest.import_from_tenderai --limit 5000   # dry run sample
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import ssl
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.dialects.postgresql import insert

_BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND / ".env")


def _tenderai_database_url() -> str:
    explicit = os.getenv("TENDERAI_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    tender_env = _BACKEND.parent.parent / "tenderai-backend" / ".env"
    if tender_env.is_file():
        for line in tender_env.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("DATABASE_URL="):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.db import get_db, init_db
from app.models.db_models import RoadContract
from app.services.geocoder import CITY_ALIASES, strip_street_prefix
from app.services.warranty import infer_warranty_years, is_road_contract_text, parse_date

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH = int(os.getenv("IMPORT_BATCH_SIZE", "500"))

_STREET_IN_TITLE = re.compile(
    r"(?:ул\.?|улица|проспект|пр-т|пр\.?|бульвар|б-р|"
    r"переулок|пер\.?|шоссе|мкр\.?|микрорайон)\s+"
    r"([А-Яа-яӘәҒғҚқҢңӨөҰұҮүІіЁёA-Za-z0-9\-\s]{2,40})",
    flags=re.IGNORECASE,
)

ROAD_SQL = """
    (
        lower(coalesce(sp.tender_title, '')) LIKE '%ремонт%'
        OR lower(coalesce(sp.tender_title, '')) LIKE '%дорог%'
        OR lower(coalesce(sp.tender_title, '')) LIKE '%покрытие%'
        OR lower(coalesce(sp.tender_title, '')) LIKE '%асфальт%'
        OR lower(coalesce(sp.tender_title, '')) LIKE '%ямочн%'
        OR lower(coalesce(sp.tender_title, '')) LIKE '%тротуар%'
        OR lower(coalesce(sp.tender_title, '')) LIKE '%автодорог%'
        OR lower(coalesce(sp.tender_title, '')) LIKE '%улиц%'
        OR lower(coalesce(sp.tender_title, '')) LIKE '%проспект%'
        OR lower(coalesce(t.description, '')) LIKE '%асфальт%'
        OR lower(coalesce(t.description, '')) LIKE '%дорог%'
    )
"""

FETCH_WINS_SQL = f"""
SELECT
    sp.tender_id,
    sp.tender_title,
    sp.supplier_name,
    sp.supplier_bin,
    sp.event_date,
    sp.region,
    sp.category,
    sp.customer_name,
    sp.amount,
    t.description,
    t.buyer,
    t.buyer_bin,
    t.region AS tender_region,
    t.budget
FROM supplier_participations sp
LEFT JOIN tenders t ON t.id = sp.tender_id
WHERE sp.is_win = true
  AND {ROAD_SQL}
ORDER BY sp.event_date DESC NULLS LAST, sp.tender_id
OFFSET $1 LIMIT $2
"""

COUNT_WINS_SQL = f"""
SELECT count(*)::int
FROM supplier_participations sp
LEFT JOIN tenders t ON t.id = sp.tender_id
WHERE sp.is_win = true AND {ROAD_SQL}
"""


def _normalize_dsn(url: str) -> str:
    u = url.strip().strip('"').strip("'")
    return u.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
        "postgres+asyncpg://", "postgresql://", 1
    )


def infer_city(title: str, customer: str, region: str | None) -> str | None:
    blob = f"{title} {customer} {region or ''}".lower()
    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            if alias in blob:
                return "Алматы" if city == "алматы" else city.capitalize()
    if region and len(region.strip()) >= 3:
        return region.strip()
    return None


def infer_street_hint(title: str) -> str | None:
    match = _STREET_IN_TITLE.search(title or "")
    if match:
        return match.group(1).strip(" ,.")
    return None


def row_from_record(rec: dict) -> dict | None:
    title = (rec.get("tender_title") or "").strip()
    if not title or not is_road_contract_text(title):
        return None

    tender_id = str(rec.get("tender_id") or "").strip()
    if not tender_id:
        return None

    customer = (rec.get("customer_name") or rec.get("buyer") or "").strip() or None
    city = infer_city(title, customer or "", rec.get("region") or rec.get("tender_region"))
    event = rec.get("event_date")
    if isinstance(event, date):
        completion = event
    else:
        completion = parse_date(event)

    years = infer_warranty_years(title, rec.get("description"), rec.get("category"))
    amount = rec.get("amount") or rec.get("budget")
    try:
        amount_int = int(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount_int = None

    return {
        "id": f"ti_{tender_id}",
        "trd_buy_id": tender_id,
        "title": title,
        "description": rec.get("description"),
        "customer_name": customer,
        "customer_bin": (rec.get("buyer_bin") or "").strip() or None,
        "supplier_name": (rec.get("supplier_name") or "").strip() or None,
        "supplier_bin": (rec.get("supplier_bin") or "").strip() or None,
        "region": city or rec.get("region") or rec.get("tender_region"),
        "city": city,
        "street_hint": infer_street_hint(title),
        "sign_date": completion,
        "completion_date": completion,
        "warranty_period_years": years,
        "contract_sum": amount_int,
        "source": "tenderai",
    }


async def _upsert_batch(rows: list[dict]) -> int:
    if not rows:
        return 0
    async with get_db() as session:
        for row in rows:
            stmt = insert(RoadContract).values(**row)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={k: v for k, v in row.items() if k != "id"},
            )
            await session.execute(stmt)
    return len(rows)


async def run_import(limit: int | None = None) -> int:
    import asyncpg

    src_url = _tenderai_database_url()
    if not src_url:
        raise RuntimeError(
            "Set TENDERAI_DATABASE_URL in talap/backend/.env "
            "(copy DATABASE_URL from tenderai-backend/.env)"
        )

    await init_db()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    conn = await asyncpg.connect(_normalize_dsn(src_url), ssl=ctx, timeout=60)
    try:
        total_available = await conn.fetchval(COUNT_WINS_SQL)
        logger.info("TenderAI road wins available: %d", total_available)

        offset = 0
        imported = 0
        cap = limit if limit is not None else total_available

        while imported < cap:
            batch_limit = min(BATCH, cap - imported)
            records = await conn.fetch(FETCH_WINS_SQL, offset, batch_limit)
            if not records:
                break

            rows: list[dict] = []
            seen_ids: set[str] = set()
            for rec in records:
                row = row_from_record(dict(rec))
                if row and row["id"] not in seen_ids:
                    seen_ids.add(row["id"])
                    rows.append(row)

            n = await _upsert_batch(rows)
            imported += n
            offset += len(records)
            logger.info("imported %d / %d (batch %d rows)", imported, cap, n)

            if len(records) < batch_limit:
                break

        return imported
    finally:
        await conn.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import road contracts from TenderAI DB")
    p.add_argument("--limit", type=int, default=None, help="Max rows to import")
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    n = await run_import(limit=args.limit)
    logger.info("Done. Imported %d road contracts from TenderAI.", n)


if __name__ == "__main__":
    asyncio.run(main())
