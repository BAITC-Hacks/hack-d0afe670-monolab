from __future__ import annotations

import unittest

from app.models.cv_schemas import Detection, SeverityTier
from app.services.cv_detector import (
    NO_DEFECT_MESSAGE,
    bbox_area,
    build_cv_response,
    classify_severity,
)


class SeverityClassificationTests(unittest.TestCase):
    def test_sunken_manhole_is_hazard(self) -> None:
        detections = [
            Detection(
                defect_class="sunken_manhole",
                confidence=0.9,
                bbox=[10.0, 10.0, 50.0, 50.0],
            )
        ]
        self.assertEqual(classify_severity(detections, 640, 480), SeverityTier.HAZARD_FASTTRACK)

    def test_large_pothole_is_hazard(self) -> None:
        detections = [
            Detection(
                defect_class="pothole",
                confidence=0.85,
                bbox=[100.0, 100.0, 300.0, 300.0],
            )
        ]
        self.assertEqual(classify_severity(detections, 1000, 1000), SeverityTier.HAZARD_FASTTRACK)

    def test_small_pothole_is_warranty_claim(self) -> None:
        detections = [
            Detection(
                defect_class="pothole",
                confidence=0.8,
                bbox=[10.0, 10.0, 60.0, 60.0],
            )
        ]
        self.assertEqual(classify_severity(detections, 1000, 1000), SeverityTier.WARRANTY_CLAIM)


class BuildResponseTests(unittest.TestCase):
    def test_no_detections_message(self) -> None:
        response = build_cv_response([], 640, 480)
        self.assertEqual(response.message, NO_DEFECT_MESSAGE)

    def test_detection_sets_primary(self) -> None:
        detections = [
            Detection(defect_class="rutting", confidence=0.7, bbox=[1.0, 2.0, 3.0, 4.0])
        ]
        response = build_cv_response(detections, 640, 480)
        self.assertEqual(response.primary_defect, "rutting")


class BboxAreaTests(unittest.TestCase):
    def test_bbox_area(self) -> None:
        self.assertEqual(bbox_area([0.0, 0.0, 10.0, 5.0]), 50.0)


if __name__ == "__main__":
    unittest.main()
