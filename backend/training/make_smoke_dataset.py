"""
Generate a tiny synthetic YOLO dataset for pipeline smoke tests (no RDD2022 required).

Usage (from talap/backend):
    python training/make_smoke_dataset.py --output training/dataset_smoke
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from training.prepare_dataset import CLASS_NAMES, CLASS_TO_ID, write_data_yaml

DEFAULT_SEED = 42
DEFAULT_PER_CLASS = 12


def _draw_pothole(draw: ImageDraw.ImageDraw, w: int, h: int) -> tuple[float, float, float, float]:
    cx, cy = random.uniform(0.25 * w, 0.75 * w), random.uniform(0.25 * h, 0.75 * h)
    rw, rh = random.uniform(0.08 * w, 0.18 * w), random.uniform(0.06 * h, 0.14 * h)
    x1, y1, x2, y2 = cx - rw, cy - rh, cx + rw, cy + rh
    draw.ellipse([x1, y1, x2, y2], fill=(40, 40, 40), outline=(20, 20, 20))
    return x1 / w, y1 / h, x2 / w, y2 / h


def _draw_crack(
    draw: ImageDraw.ImageDraw, w: int, h: int, vertical: bool
) -> tuple[float, float, float, float]:
    if vertical:
        x = random.uniform(0.3 * w, 0.7 * w)
        y1, y2 = 0.15 * h, 0.85 * h
        draw.line([(x, y1), (x + random.uniform(-8, 8), y2)], fill=(30, 30, 30), width=4)
        return (x - 10) / w, y1 / h, (x + 10) / w, y2 / h
    # alligator patch
    x1, y1 = 0.2 * w, 0.35 * h
    x2, y2 = 0.8 * w, 0.65 * h
    for _ in range(8):
        draw.line(
            [
                (random.uniform(x1, x2), random.uniform(y1, y2)),
                (random.uniform(x1, x2), random.uniform(y1, y2)),
            ],
            fill=(35, 35, 35),
            width=2,
        )
    return x1 / w, y1 / h, x2 / w, y2 / h


def _draw_manhole(draw: ImageDraw.ImageDraw, w: int, h: int) -> tuple[float, float, float, float]:
    cx, cy = random.uniform(0.3 * w, 0.7 * w), random.uniform(0.3 * h, 0.7 * h)
    r = random.uniform(0.06 * w, 0.12 * w)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(50, 50, 55), outline=(10, 10, 10), width=3)
    return (cx - r) / w, (cy - r) / h, (cx + r) / w, (cy + r) / h


def _draw_rutting(draw: ImageDraw.ImageDraw, w: int, h: int) -> tuple[float, float, float, float]:
    y = random.uniform(0.4 * h, 0.6 * h)
    draw.rectangle([0.1 * w, y - 15, 0.9 * w, y + 15], fill=(90, 85, 80))
    return 0.1, (y - 15) / h, 0.9, (y + 15) / h


def _to_yolo(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float, float, float]:
    xc = (x1 + x2) / 2
    yc = (y1 + y2) / 2
    bw = max(0.01, x2 - x1)
    bh = max(0.01, y2 - y1)
    return xc, yc, bw, bh


def _make_image(class_name: str, size: int = 640) -> tuple[Image.Image, tuple[float, float, float, float]]:
    img = Image.new("RGB", (size, size), (120, 118, 115))
    draw = ImageDraw.Draw(img)
    w, h = size, size

    if class_name == "pothole":
        box = _draw_pothole(draw, w, h)
    elif class_name == "crack_longitudinal":
        box = _draw_crack(draw, w, h, vertical=True)
    elif class_name == "crack_alligator":
        box = _draw_crack(draw, w, h, vertical=False)
    elif class_name == "sunken_manhole":
        box = _draw_manhole(draw, w, h)
    elif class_name == "rutting":
        box = _draw_rutting(draw, w, h)
    else:
        raise ValueError(class_name)

    return img, _to_yolo(*box)


def _write_split(
    output_dir: Path,
    split: str,
    class_name: str,
    count: int,
    seed: int,
) -> int:
    rng = random.Random(seed)
    class_id = CLASS_TO_ID[class_name]
    images_dir = output_dir / "images" / split
    labels_dir = output_dir / "labels" / split
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for i in range(count):
        img, (xc, yc, bw, bh) = _make_image(class_name)
        # slight color jitter
        pixels = img.load()
        for _ in range(200):
            x, y = rng.randint(0, img.width - 1), rng.randint(0, img.height - 1)
            r, g, b = pixels[x, y]
            pixels[x, y] = (
                max(0, min(255, r + rng.randint(-15, 15))),
                max(0, min(255, g + rng.randint(-15, 15))),
                max(0, min(255, b + rng.randint(-15, 15))),
            )
        stem = f"smoke_{class_name}_{split}_{i:03d}"
        img.save(images_dir / f"{stem}.jpg", quality=90)
        (labels_dir / f"{stem}.txt").write_text(
            f"{class_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}\n",
            encoding="utf-8",
        )
        written += 1
    return written


def make_smoke_dataset(
    output_dir: Path,
    per_class: int = DEFAULT_PER_CLASS,
    split_ratios: tuple[float, float, float] = (0.70, 0.15, 0.15),
    seed: int = DEFAULT_SEED,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    train_n = max(1, int(per_class * split_ratios[0]))
    val_n = max(1, int(per_class * split_ratios[1]))
    test_n = max(1, int(per_class * split_ratios[2]))

    total = 0
    for idx, class_name in enumerate(CLASS_NAMES):
        total += _write_split(output_dir, "train", class_name, train_n, seed + idx)
        total += _write_split(output_dir, "val", class_name, val_n, seed + idx + 100)
        total += _write_split(output_dir, "test", class_name, test_n, seed + idx + 200)

    yaml_path = write_data_yaml(output_dir, include_test=True)
    print(f"Smoke dataset: {total} images → {output_dir}")
    print(f"  train ~{train_n * len(CLASS_NAMES)}, val ~{val_n * len(CLASS_NAMES)}, test ~{test_n * len(CLASS_NAMES)}")
    print(f"  {yaml_path}")
    return yaml_path


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Synthetic YOLO smoke dataset for Talap")
    parser.add_argument("--output", type=Path, default=Path("training/dataset_smoke"))
    parser.add_argument("--per-class", type=int, default=DEFAULT_PER_CLASS)
    parser.add_argument("--split-ratios", type=str, default="0.70,0.15,0.15")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    from training.split_utils import parse_split_ratios

    make_smoke_dataset(
        args.output,
        per_class=args.per_class,
        split_ratios=parse_split_ratios(args.split_ratios),
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
