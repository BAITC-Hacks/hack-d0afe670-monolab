#!/usr/bin/env python3
"""
Smoke-test CV inference locally (no server required).

Usage (from talap/backend):
    python scripts/test_cv_inference.py
    python scripts/test_cv_inference.py --image path/to/photo.jpg
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.cv_detector import get_cv_detector


async def run(image_path: Path) -> None:
    detector = get_cv_detector()
    await detector.initialize()

    if not detector.is_ready:
        print(f"CV model NOT ready: {detector.load_error}")
        sys.exit(1)

    image_bytes = image_path.read_bytes()
    result = await detector.detect(image_bytes)

    print(f"image: {image_path}")
    print(f"message: {result.message}")
    print(f"primary_defect: {result.primary_defect}")
    print(f"severity_tier: {result.severity_tier}")
    print(f"detections ({len(result.detections)}):")
    for det in result.detections:
        print(f"  - {det.defect_class}: conf={det.confidence:.3f} bbox={det.bbox}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Talap CV inference")
    default_image = _BACKEND / "training" / "dataset_smoke" / "images" / "val" / "smoke_pothole_val_000.jpg"
    parser.add_argument("--image", type=Path, default=default_image)
    args = parser.parse_args()

    if not args.image.is_file():
        print(f"Image not found: {args.image}")
        print("Run: python training/make_smoke_dataset.py first")
        sys.exit(1)

    asyncio.run(run(args.image))


if __name__ == "__main__":
    main()
