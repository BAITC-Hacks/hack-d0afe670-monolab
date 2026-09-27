from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SeverityTier(str, Enum):
    HAZARD_FASTTRACK = "HAZARD_FASTTRACK"
    WARRANTY_CLAIM = "WARRANTY_CLAIM"


class Detection(BaseModel):
    defect_class: str = Field(
        ...,
        description="One of: pothole, crack_longitudinal, crack_alligator, sunken_manhole, rutting",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: List[float] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Axis-aligned box [x1, y1, x2, y2] in pixel coordinates",
    )


class CVDetectionResponse(BaseModel):
    detections: List[Detection] = Field(default_factory=list)
    severity_tier: Optional[SeverityTier] = None
    primary_defect: Optional[str] = None
    message: str
