from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.models.cv_schemas import CVDetectionResponse, SeverityTier
from app.models.schemas import MatchResponse


class DefectReportResponse(BaseModel):
    """Combined CV detection + warranty contract match for a field report."""

    cv: CVDetectionResponse
    match: Optional[MatchResponse] = None
    severity_tier: Optional[SeverityTier] = Field(
        default=None,
        description="Routing decision from CV post-processing (mirrors cv.severity_tier)",
    )
    message: str
