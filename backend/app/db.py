from __future__ import annotations

import logging
import os
import ssl
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_backend_root = Path(__file__).resolve().parents[1]
load_dotenv(_backend_root / ".env")
load_dotenv()

logger = logging.getLogger(__name__)

_raw = os.getenv("DATABASE_URL", "").strip()
if _raw.startswith("postgres://"):
    DATABASE_URL = _raw.replace("postgres://", "postgresql+asyncpg://", 1)
elif _raw.startswith("postgresql://") and "+asyncpg" not in _raw:
    DATABASE_URL = _raw.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = _raw

DB_AVAILABLE = bool(DATABASE_URL)

_ssl = ssl.create_default_context()
_ssl.check_hostname = False
_ssl.verify_mode = ssl.CERT_NONE

_engine = None
_session_factory = None


class Base(DeclarativeBase):
    pass


def get_engine():
    global _engine
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    if _engine is None:
        connect_args: dict = {
            "prepared_statement_cache_size": 0,
            "statement_cache_size": 0,
        }
        if os.getenv("DATABASE_SSL", "1").strip().lower() not in ("0", "false", "no"):
            connect_args["ssl"] = _ssl
        _engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            pool_size=int(os.getenv("DB_POOL_SIZE", "3")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        host = urlparse(DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")).hostname
        logger.info("Talap DB ready host=%s", host)
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set — API will return empty matches until DB is configured")
        return
    from app.models import db_models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "ALTER TABLE road_contracts "
                "ALTER COLUMN contract_sum TYPE BIGINT USING contract_sum::bigint"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE street_geocache "
                "ADD COLUMN IF NOT EXISTS polyline_json TEXT"
            )
        )
    logger.info("Talap schema ready")
