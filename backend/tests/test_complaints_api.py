from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.complaint_schemas import ComplaintStatus, ComplaintTier


@pytest.fixture
def client():
    return TestClient(app)


def test_specialist_list_requires_key(client):
    res = client.get("/api/v1/specialist/complaints")
    assert res.status_code in (401, 503)


@patch("app.api.routes.complaints.get_db")
@patch("app.api.routes.complaints.get_cv_detector")
@patch("app.api.routes.complaints.MatcherService")
@patch("app.api.routes.complaints.reverse_geocode")
@patch("app.api.routes.complaints.create_complaint_from_report")
def test_submit_citizen_response_has_no_warranty_fields(
    mock_create,
    mock_geo,
    mock_matcher,
    mock_detector,
    mock_get_db,
    client,
):
    from app.models.cv_schemas import CVDetectionResponse, Detection, SeverityTier

    detector = MagicMock()
    detector.is_ready = True
    detector.detect = AsyncMock(
        return_value=CVDetectionResponse(
            detections=[
                Detection(
                    defect_class="pothole",
                    confidence=0.8,
                    bbox=[10, 10, 100, 100],
                )
            ],
            severity_tier=SeverityTier.WARRANTY_CLAIM,
            primary_defect="pothole",
            message="defect_detected",
        )
    )
    mock_detector.return_value = detector

    geo = MagicMock()
    geo.display_name = "г. Алматы, ул. Абая"
    mock_geo.return_value = geo

    matcher = MagicMock()
    matcher.match = AsyncMock()
    mock_matcher.return_value = matcher

    complaint = MagicMock()
    complaint.service_request_id = "TLP-2026-000099"
    complaint.status = ComplaintStatus.REGISTERED.value
    complaint.response_deadline = datetime.now(timezone.utc)
    complaint.agency_responsible = "Акимат"
    mock_create.return_value = complaint

    session = AsyncMock()
    mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
    mock_get_db.return_value.__aexit__ = AsyncMock(return_value=None)

    res = client.post(
        "/api/v1/complaints",
        files={"file": ("test.jpg", b"fake-image", "image/jpeg")},
        data={"lat": "43.24", "lng": "76.91", "description": "Яма"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["service_request_id"] == "TLP-2026-000099"
    for key in ("contract_id", "contractor_name", "contractor_bin", "warranty_end", "tier", "simulated"):
        assert key not in body


@patch("app.api.routes.specialist.SPECIALIST_API_KEY", "test-key")
@patch("app.api.routes.specialist.get_db")
@patch("app.api.routes.specialist.approve_complaint")
@patch("app.api.routes.specialist.get_complaint_by_id")
def test_approve_warranty_vs_general_paths(
    mock_get,
    mock_approve,
    mock_get_db,
    client,
):
    session = AsyncMock()
    mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
    mock_get_db.return_value.__aexit__ = AsyncMock(return_value=None)

    warranty_complaint = MagicMock()
    warranty_complaint.id = 1
    warranty_complaint.service_request_id = "TLP-2026-000001"
    warranty_complaint.status = ComplaintStatus.FORWARDED.value
    warranty_complaint.tier = ComplaintTier.WARRANTY_CLAIM.value
    mock_get.return_value = warranty_complaint
    mock_approve.return_value = warranty_complaint

    res = client.post(
        "/api/v1/specialist/complaints/1/approve",
        headers={"X-Specialist-Key": "test-key"},
        json={"note": "ok"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "FORWARDED"
