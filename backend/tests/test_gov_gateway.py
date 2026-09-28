from datetime import date

import pytest

from app.models.complaint_schemas import ComplaintTier
from app.services.complaint_workflow import VALID_TRANSITIONS, assert_transition, decide_tier
from app.services.gov_gateway import InternalGovGateway, add_working_days


def test_add_working_days_skips_weekends():
    # Monday 2026-09-28 + 15 working days
    start = date(2026, 9, 28)
    deadline = add_working_days(start, 15)
    assert deadline.weekday() < 5
    assert (deadline - start).days >= 15


def test_internal_gateway_registration_flow():
    import asyncio

    async def _run():
        gw = InternalGovGateway()
        r1 = await gw.submit(
            service_request_id="TLP-2026-000001",
            tier=ComplaintTier.GENERAL_MAINTENANCE_REQUEST,
            service_code="pothole",
            address="ул. Абая",
            description="test",
        )
        r2 = await gw.submit(
            service_request_id="TLP-2026-000002",
            tier=ComplaintTier.HAZARD_FASTTRACK,
            service_code="sunken_manhole",
            address="ул. Толе би",
            description="test2",
        )
        assert r1.agency_responsible != ""
        assert r2.agency_responsible != ""

    asyncio.run(_run())


def test_state_machine_rejects_invalid_transition():
    from fastapi import HTTPException

    from app.models.complaint_schemas import ComplaintStatus

    with pytest.raises(HTTPException) as exc:
        assert_transition(ComplaintStatus.SUBMITTED, ComplaintStatus.FORWARDED)
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException):
        assert_transition(ComplaintStatus.RESOLVED, ComplaintStatus.FORWARDED)


def test_decide_tier_general_when_no_warranty():
    from app.models.cv_schemas import SeverityTier
    from app.models.schemas import MatchResponse

    tier = decide_tier(
        SeverityTier.WARRANTY_CLAIM,
        MatchResponse(match_found=False, message="no_match"),
    )
    assert tier.value == "GENERAL_MAINTENANCE_REQUEST"


def test_citizen_response_schema_has_no_warranty_keys():
    from app.models.complaint_schemas import CitizenComplaintSubmitResponse, ComplaintStatus
    from datetime import datetime, timezone

    payload = CitizenComplaintSubmitResponse(
        service_request_id="TLP-2026-000001",
        status=ComplaintStatus.REGISTERED,
        response_deadline=datetime.now(timezone.utc),
        agency_responsible="Акимат",
    ).model_dump()
    forbidden = {"contract_id", "contractor_name", "contractor_bin", "warranty_end"}
    assert forbidden.isdisjoint(payload.keys())
