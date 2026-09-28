from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.config import GOV_GATEWAY
from app.models.complaint_schemas import ComplaintTier

# Tier / defect → responsible agency (routing table until Smart Bridge API is wired).
AGENCY_BY_TIER: dict[ComplaintTier, str] = {
    ComplaintTier.HAZARD_FASTTRACK: (
        "Управление городской мобильности г. Алматы — аварийная служба"
    ),
    ComplaintTier.WARRANTY_CLAIM: (
        "Акимат г. Алматы — отдел контроля гарантийных обязательств"
    ),
    ComplaintTier.GENERAL_MAINTENANCE_REQUEST: (
        "Акимат г. Алматы — отдел содержания дорог"
    ),
}

AGENCY_BY_DEFECT: dict[str, str] = {
    "sunken_manhole": "Управление городской мобильности г. Алматы — колодцы",
    "pothole": "Акимат г. Алматы — отдел содержания дорог",
    "crack_longitudinal": "Акимат г. Алматы — отдел содержания дорог",
    "crack_alligator": "Акимат г. Алматы — отдел содержания дорог",
    "rutting": "Акимат г. Алматы — отдел содержания дорог",
}


@dataclass(frozen=True)
class GatewayReceipt:
    registered_at: datetime
    response_deadline: datetime
    agency_responsible: str


class GovGateway(ABC):
    @abstractmethod
    async def submit(
        self,
        *,
        service_request_id: str,
        tier: ComplaintTier,
        service_code: str,
        address: str,
        description: str,
    ) -> GatewayReceipt:
        ...

    @abstractmethod
    async def get_status(self, service_request_id: str) -> dict:
        ...


def add_working_days(start: date, working_days: int) -> date:
    """Add working days, skipping weekends (holidays ignored)."""
    current = start
    added = 0
    while added < working_days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def pick_agency(tier: ComplaintTier, service_code: str) -> str:
    return AGENCY_BY_DEFECT.get(service_code) or AGENCY_BY_TIER[tier]


class InternalGovGateway(GovGateway):
    """
    Talap-native registration: assigns agency + SLA deadline and persists via complaint workflow.
    Replace with SmartBridgeGateway when national API credentials are available.
    """

    RESPONSE_WORKING_DAYS = 15

    async def submit(
        self,
        *,
        service_request_id: str,
        tier: ComplaintTier,
        service_code: str,
        address: str,
        description: str,
    ) -> GatewayReceipt:
        now = datetime.now(timezone.utc)
        deadline = add_working_days(now.date(), self.RESPONSE_WORKING_DAYS)
        return GatewayReceipt(
            registered_at=now,
            response_deadline=datetime(
                deadline.year, deadline.month, deadline.day, tzinfo=timezone.utc
            ),
            agency_responsible=pick_agency(tier, service_code),
        )

    async def get_status(self, service_request_id: str) -> dict:
        return {
            "service_request_id": service_request_id,
            "gateway": "internal",
        }


def get_gov_gateway() -> GovGateway:
    mode = GOV_GATEWAY
    if mode in ("internal", "mock", ""):
        return InternalGovGateway()
    if mode == "smart_bridge":
        raise NotImplementedError(
            "GOV_GATEWAY=smart_bridge is not implemented yet. Use GOV_GATEWAY=internal."
        )
    raise ValueError(f"Unknown GOV_GATEWAY: {mode}")
