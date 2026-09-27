from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, List, Optional, Tuple

from app.config import (
    CV_CONFIDENCE_THRESHOLD,
    CV_MODEL_PATH,
    CV_POTHOLE_HAZARD_AREA_RATIO,
    MODAL_CV_APP_NAME,
    MODAL_CV_FUNCTION_NAME,
    USE_MODAL,
)
from app.models.cv_schemas import CVDetectionResponse, Detection, SeverityTier

logger = logging.getLogger(__name__)

DEFECT_CLASSES: Tuple[str, ...] = (
    "pothole",
    "crack_longitudinal",
    "crack_alligator",
    "sunken_manhole",
    "rutting",
)

NO_DEFECT_MESSAGE = "no_defect_detected"


def bbox_area(bbox: List[float]) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def classify_severity(
    detections: List[Detection],
    image_width: int,
    image_height: int,
    pothole_hazard_area_ratio: float = CV_POTHOLE_HAZARD_AREA_RATIO,
) -> Optional[SeverityTier]:
    """
    Post-processing severity routing (not part of the YOLO head).

    HAZARD_FASTTRACK:
      - sunken_manhole (always — immediate safety hazard)
      - pothole whose bbox covers > pothole_hazard_area_ratio of the image
        (default 2% — tune with KZ field photos; larger ratio = fewer fast-tracks)

    WARRANTY_CLAIM:
      - crack_longitudinal, crack_alligator, rutting
      - small potholes below the area threshold
    """
    if not detections or image_width <= 0 or image_height <= 0:
        return None

    image_area = float(image_width * image_height)
    hazard_threshold = image_area * pothole_hazard_area_ratio

    for det in detections:
        if det.defect_class == "sunken_manhole":
            return SeverityTier.HAZARD_FASTTRACK
        if det.defect_class == "pothole" and bbox_area(det.bbox) >= hazard_threshold:
            return SeverityTier.HAZARD_FASTTRACK

    return SeverityTier.WARRANTY_CLAIM


def _parse_local_results(
    results: Any,
    confidence_threshold: float,
) -> Tuple[List[Detection], int, int]:
    detections: List[Detection] = []
    if not results:
        return detections, 0, 0

    result = results[0]
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        shape = getattr(result, "orig_shape", (0, 0))
        return detections, int(shape[1]), int(shape[0])

    shape = getattr(result, "orig_shape", (0, 0))
    img_h, img_w = int(shape[0]), int(shape[1])

    for box in boxes:
        conf = float(box.conf[0])
        if conf < confidence_threshold:
            continue
        cls_id = int(box.cls[0])
        if cls_id < 0 or cls_id >= len(DEFECT_CLASSES):
            continue
        x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
        detections.append(
            Detection(
                defect_class=DEFECT_CLASSES[cls_id],
                confidence=round(conf, 4),
                bbox=[x1, y1, x2, y2],
            )
        )

    detections.sort(key=lambda d: d.confidence, reverse=True)
    return detections, img_w, img_h


def build_cv_response(
    detections: List[Detection],
    image_width: int,
    image_height: int,
) -> CVDetectionResponse:
    if not detections:
        return CVDetectionResponse(
            detections=[],
            severity_tier=None,
            primary_defect=None,
            message=NO_DEFECT_MESSAGE,
        )

    severity = classify_severity(detections, image_width, image_height)
    primary = detections[0].defect_class
    return CVDetectionResponse(
        detections=detections,
        severity_tier=severity,
        primary_defect=primary,
        message="defect_detected",
    )


class CVDetectorService:
    """Singleton YOLO inference service — model loaded once at startup."""

    _instance: Optional["CVDetectorService"] = None

    def __init__(self) -> None:
        self._model: Any = None
        self._loaded = False
        self._load_error: Optional[str] = None
        self._modal_fn: Any = None

    @classmethod
    def get_instance(cls) -> "CVDetectorService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def is_ready(self) -> bool:
        if USE_MODAL:
            return self._modal_fn is not None
        return self._loaded and self._model is not None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    async def initialize(self) -> None:
        if USE_MODAL:
            await self._initialize_modal()
            return
        await self._initialize_local()

    async def _initialize_modal(self) -> None:
        try:
            import modal  # type: ignore[import-untyped]

            self._modal_fn = modal.Function.lookup(
                MODAL_CV_APP_NAME,
                MODAL_CV_FUNCTION_NAME,
            )
            self._loaded = True
            logger.info(
                "CV detector configured for Modal (%s.%s)",
                MODAL_CV_APP_NAME,
                MODAL_CV_FUNCTION_NAME,
            )
        except Exception as exc:
            self._load_error = str(exc)
            logger.error("Modal CV function lookup failed: %s", exc, exc_info=True)

    async def _initialize_local(self) -> None:
        weights = Path(CV_MODEL_PATH)
        if not weights.is_file():
            self._load_error = f"CV weights not found at {weights}"
            logger.warning(self._load_error)
            return

        try:
            loop = asyncio.get_running_loop()
            self._model = await loop.run_in_executor(None, self._load_model_sync, weights)
            self._loaded = True
            logger.info("CV YOLO model loaded from %s", weights)
        except Exception as exc:
            self._load_error = str(exc)
            logger.error("Failed to load CV model: %s", exc, exc_info=True)

    @staticmethod
    def _load_model_sync(weights: Path) -> Any:
        from ultralytics import YOLO  # type: ignore[import-untyped]

        return YOLO(str(weights))

    async def detect(self, image_bytes: bytes) -> CVDetectionResponse:
        if not self.is_ready:
            raise RuntimeError(
                self._load_error or "CV model is not loaded. Set CV_MODEL_PATH or USE_MODAL=true."
            )

        if USE_MODAL:
            return await self._detect_modal(image_bytes)
        return await self._detect_local(image_bytes)

    async def _detect_modal(self, image_bytes: bytes) -> CVDetectionResponse:
        loop = asyncio.get_running_loop()
        payload = await loop.run_in_executor(
            None,
            lambda: self._modal_fn.remote(image_bytes, CV_CONFIDENCE_THRESHOLD),
        )
        detections = [Detection(**d) for d in payload.get("detections", [])]
        return build_cv_response(
            detections,
            int(payload.get("image_width", 0)),
            int(payload.get("image_height", 0)),
        )

    async def _detect_local(self, image_bytes: bytes) -> CVDetectionResponse:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._detect_sync, image_bytes)

    def _detect_sync(self, image_bytes: bytes) -> CVDetectionResponse:
        from PIL import Image

        image = Image.open(BytesIO(image_bytes))
        image_width, image_height = image.size

        results = self._model.predict(
            source=image,
            conf=CV_CONFIDENCE_THRESHOLD,
            verbose=False,
        )
        detections, img_w, img_h = _parse_local_results(results, CV_CONFIDENCE_THRESHOLD)
        width = image_width or img_w
        height = image_height or img_h
        return build_cv_response(detections, width, height)


@lru_cache(maxsize=1)
def get_cv_detector() -> CVDetectorService:
    return CVDetectorService.get_instance()
