from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.config import GOSZAKUP_GRAPHQL_URL, GOSZAKUP_TOKEN

logger = logging.getLogger(__name__)

CONTRACTS_BY_DATE_GQL = """
query TalapContracts($limit: Int!, $filter: ContractFiltersInput!) {
  Contract(limit: $limit, filter: $filter) {
    id
    trdBuyId
    trdBuyNameRu
    contractSum
    signDate
    supplierBiin
    customerBin
    Supplier { nameRu }
    Customer { nameRu }
  }
}
"""

CONTRACT_BY_BUY_GQL = """
query TalapContractByBuy($trdBuyId: Int!) {
  Contract(limit: 1, filter: { trdBuyId: [$trdBuyId] }) {
    id
    trdBuyId
    trdBuyNameRu
    signDate
    supplierBiin
    Supplier { nameRu }
    Customer { nameRu }
  }
}
"""


def auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {GOSZAKUP_TOKEN}",
        "Content-Type": "application/json",
    }


def pick(item: dict, *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


async def fetch_contracts_signed_between(
    client: httpx.AsyncClient,
    *,
    sign_from: str,
    sign_to: str,
    limit: int = 200,
) -> list[dict]:
    if not GOSZAKUP_TOKEN:
        return []
    try:
        resp = await client.post(
            GOSZAKUP_GRAPHQL_URL,
            json={
                "query": CONTRACTS_BY_DATE_GQL,
                "variables": {
                    "limit": limit,
                    "filter": {"signDate": [sign_from, sign_to]},
                },
            },
            headers=auth_headers(),
            timeout=25.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            logger.warning("Goszakup GraphQL errors: %s", payload["errors"][:1])
            return []
        items = (payload.get("data") or {}).get("Contract") or []
        return items if isinstance(items, list) else []
    except Exception as exc:
        logger.warning("contract fetch %s..%s failed: %s", sign_from, sign_to, exc)
        return []


async def fetch_contract_by_buy_id(trd_buy_id: str | int) -> Optional[dict]:
    if not GOSZAKUP_TOKEN:
        return None
    try:
        buy_id = int(trd_buy_id)
    except (TypeError, ValueError):
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                GOSZAKUP_GRAPHQL_URL,
                json={
                    "query": CONTRACT_BY_BUY_GQL,
                    "variables": {"trdBuyId": buy_id},
                },
                headers=auth_headers(),
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.debug("contract by buy failed id=%s: %s", trd_buy_id, exc)
        return None
    if payload.get("errors"):
        return None
    items = (payload.get("data") or {}).get("Contract") or []
    if isinstance(items, list) and items:
        return items[0]
    return None
