"""API tests for CV endpoints (uses mocked detector — no weights required)."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.models.cv_schemas import CVDetectionResponse, Detection, SeverityTier


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (100, 100, 100)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def client():
    return TestClient(app)


def test_cv_detect_returns_503_when_model_not_ready(client):
    mock_detector = MagicMock()
    mock_detector.is_ready = False
    mock_detector.load_error = "weights missing"

    with patch("app.api.routes.cv.get_cv_detector", return_value=mock_detector):
        res = client.post(
            "/api/v1/cv/detect",
            files={"file": ("test.jpg", _jpeg_bytes(), "image/jpeg")},
        )
    assert res.status_code == 503


def test_cv_detect_success(client):
    mock_detector = MagicMock()
    mock_detector.is_ready = True
    mock_detector.detect = AsyncMock(
        return_value=CVDetectionResponse(
            detections=[
                Detection(
                    defect_class="pothole",
                    confidence=0.91,
                    bbox=[10.0, 10.0, 50.0, 50.0],
                )
            ],
            severity_tier=SeverityTier.WARRANTY_CLAIM,
            primary_defect="pothole",
            message="defect_detected",
        )
    )

    with patch("app.api.routes.cv.get_cv_detector", return_value=mock_detector):
        res = client.post(
            "/api/v1/cv/detect",
            files={"file": ("test.jpg", _jpeg_bytes(), "image/jpeg")},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["primary_defect"] == "pothole"
    assert data["message"] == "defect_detected"


def test_cv_detect_rejects_png_content_type_mismatch(client):
    mock_detector = MagicMock()
    mock_detector.is_ready = True

    with patch("app.api.routes.cv.get_cv_detector", return_value=mock_detector):
        res = client.post(
            "/api/v1/cv/detect",
            files={"file": ("test.gif", _jpeg_bytes(), "image/gif")},
        )
    assert res.status_code == 400
