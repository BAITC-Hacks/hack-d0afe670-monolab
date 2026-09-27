"""
Modal GPU deployment for Talap road-defect CV inference.

Deploy (from talap/backend):
    modal deploy deploy/modal_app.py

Set in .env:
    USE_MODAL=true
    MODAL_CV_APP_NAME=talap-cv
    MODAL_CV_FUNCTION_NAME=detect
"""

from __future__ import annotations

import modal

APP_NAME = "talap-cv"
VOLUME_NAME = "talap-cv-weights"
WEIGHTS_PATH = "/weights/best.pt"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("ultralytics", "pillow", "numpy")
)

app = modal.App(APP_NAME)
weights_volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

DEFECT_CLASSES = [
    "pothole",
    "crack_longitudinal",
    "crack_alligator",
    "sunken_manhole",
    "rutting",
]


@app.function(
    gpu="T4",
    image=image,
    volumes={"/weights": weights_volume},
    timeout=120,
)
def detect(image_bytes: bytes, confidence: float = 0.4) -> dict:
    from io import BytesIO

    from PIL import Image
    from ultralytics import YOLO

    model = YOLO(WEIGHTS_PATH)
    pil_image = Image.open(BytesIO(image_bytes))
    width, height = pil_image.size

    results = model.predict(source=pil_image, conf=confidence, verbose=False)
    detections: list[dict] = []

    if results and results[0].boxes is not None:
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            if cls_id < 0 or cls_id >= len(DEFECT_CLASSES):
                continue
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
            detections.append(
                {
                    "defect_class": DEFECT_CLASSES[cls_id],
                    "confidence": round(float(box.conf[0]), 4),
                    "bbox": [x1, y1, x2, y2],
                }
            )

    detections.sort(key=lambda d: d["confidence"], reverse=True)
    return {
        "detections": detections,
        "image_width": width,
        "image_height": height,
    }
