"""
Download the BITS manhole_detection Roboflow Universe export (YOLOv8).

Requires a free Roboflow API key: https://app.roboflow.com/settings/api

Usage (from talap/backend):
    export ROBOFLOW_API_KEY=your_key
    PYTHONPATH=. python training/download_roboflow_manhole.py
    PYTHONPATH=. python training/download_roboflow_manhole.py --output /Users/darkhan/data/roboflow_manhole
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

DEFAULT_OUTPUT = Path("/Users/darkhan/data/roboflow_manhole")
DATASET_URL = "https://universe.roboflow.com/bits-gtqdp/manhole_detection-wdc0v/1"


def main() -> None:
    parser = argparse.ArgumentParser(description="Download BITS manhole_detection YOLOv8 export")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Download destination (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--dataset-url",
        default=DATASET_URL,
        help="Roboflow Universe dataset version URL",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ROBOFLOW_API_KEY")
    if not api_key:
        raise SystemExit(
            "ROBOFLOW_API_KEY is not set. Create a free key at "
            "https://app.roboflow.com/settings/api then:\n"
            "  export ROBOFLOW_API_KEY=your_key"
        )

    from roboflow import Roboflow, download_dataset

    args.output.mkdir(parents=True, exist_ok=True)
    rf = Roboflow(api_key=api_key)
    _ = rf  # login validation
    dataset = download_dataset(
        dataset_url=args.dataset_url,
        model_format="yolov8",
        location=str(args.output),
    )
    print(f"Downloaded to: {dataset.location}")


if __name__ == "__main__":
    main()
