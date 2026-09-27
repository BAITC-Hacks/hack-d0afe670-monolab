"""
Post-training sanity check: visual + severity-tier review for demo readiness.

Runs inference on curated samples (per-class from dataset_v1 val by default),
compares to ground-truth labels where available, and flags demo risks.

Usage (from talap/backend, after training finishes):
    PYTHONPATH=. python training/sanity_check_model.py
    PYTHONPATH=. python training/sanity_check_model.py \\
        --weights runs/detect/training/runs/single_stage/weights/best.pt \\
        --data training/dataset_v1/data.yaml \\
        --samples-per-class 5 \\
        --conf 0.4 \\
        --output training/sanity_output
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from enum import Enum

from training.prepare_dataset import CLASS_NAMES

DEFECT_CLASSES = tuple(CLASS_NAMES)


class SeverityTier(str, Enum):
    HAZARD_FASTTRACK = "HAZARD_FASTTRACK"
    WARRANTY_CLAIM = "WARRANTY_CLAIM"


@dataclass
class Detection:
    defect_class: str
    confidence: float
    bbox: List[float]


def bbox_area(bbox: List[float]) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def classify_severity(
    detections: List[Detection],
    image_width: int,
    image_height: int,
    pothole_hazard_area_ratio: float = 0.02,
) -> Optional[SeverityTier]:
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


@dataclass
class CVDetectionResponse:
    detections: List[Detection]
    severity_tier: Optional[SeverityTier]
    primary_defect: Optional[str]
    message: str


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
            message="no_defect_detected",
        )
    severity = classify_severity(detections, image_width, image_height)
    primary = detections[0].defect_class
    return CVDetectionResponse(
        detections=detections,
        severity_tier=severity,
        primary_defect=primary,
        message="ok",
    )

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class SampleResult:
    image: Path
    split: str
    gt_classes: Set[str]
    pred_classes: Set[str]
    detections: List[Detection]
    severity_tier: Optional[str]
    primary_defect: Optional[str]
    demo_flags: List[str] = field(default_factory=list)


def _read_gt_classes(label_path: Path) -> Set[str]:
    classes: Set[str] = set()
    if not label_path.is_file():
        return classes
    for line in label_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        cid = int(line.split()[0])
        if 0 <= cid < len(CLASS_NAMES):
            classes.add(CLASS_NAMES[cid])
    return classes


def _find_image_for_stem(images_dir: Path, stem: str) -> Optional[Path]:
    for suffix in IMAGE_SUFFIXES:
        candidate = images_dir / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def collect_samples(
    dataset_root: Path,
    splits: Sequence[str],
    samples_per_class: int,
) -> List[Tuple[Path, Path, str, Set[str]]]:
    """Return (image_path, label_path, split, gt_classes) per class."""
    by_class: Dict[str, List[Tuple[Path, Path, str, Set[str]]]] = defaultdict(list)

    for split in splits:
        labels_dir = dataset_root / "labels" / split
        images_dir = dataset_root / "images" / split
        if not labels_dir.is_dir():
            continue
        for label_path in sorted(labels_dir.glob("*.txt")):
            gt = _read_gt_classes(label_path)
            if not gt:
                continue
            image_path = _find_image_for_stem(images_dir, label_path.stem)
            if image_path is None:
                continue
            for cls_name in gt:
                if len(by_class[cls_name]) < samples_per_class:
                    by_class[cls_name].append((image_path, label_path, split, gt))

    samples: List[Tuple[Path, Path, str, Set[str]]] = []
    seen: Set[Path] = set()
    for cls_name in CLASS_NAMES:
        for item in by_class.get(cls_name, []):
            if item[0] not in seen:
                samples.append(item)
                seen.add(item[0])
    return samples


def _parse_yolo_results(results, conf_threshold: float) -> Tuple[List[Detection], int, int]:
    detections: List[Detection] = []
    if not results:
        return detections, 0, 0
    result = results[0]
    boxes = getattr(result, "boxes", None)
    shape = getattr(result, "orig_shape", (0, 0))
    img_h, img_w = int(shape[0]), int(shape[1])
    if boxes is None or len(boxes) == 0:
        return detections, img_w, img_h
    for box in boxes:
        conf = float(box.conf[0])
        if conf < conf_threshold:
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


def _demo_flags(
    gt: Set[str],
    pred: Set[str],
    severity: Optional[str],
    detections: List[Detection],
    conf: float,
    img_w: int,
    img_h: int,
) -> List[str]:
    flags: List[str] = []
    if not pred and gt:
        flags.append("MISS: model silent on labeled defect(s)")
    if pred and not gt.intersection(pred):
        flags.append("CLASS_MISMATCH: detected but wrong class vs label")
    if "sunken_manhole" in gt and "sunken_manhole" not in pred:
        flags.append("DEMO_RISK: missed manhole — fast-track would not fire")
    if "sunken_manhole" in pred and severity != "HAZARD_FASTTRACK":
        flags.append("SEVERITY_BUG: manhole detected but not fast-tracked")
    if "pothole" in gt:
        for det in detections:
            if det.defect_class == "pothole":
                ratio = bbox_area(det.bbox) / max(1, img_w * img_h)
                if ratio >= 0.02 and severity != "HAZARD_FASTTRACK":
                    flags.append(
                        f"SEVERITY_TUNE: large pothole ({ratio:.1%} area) not fast-tracked at conf={conf}"
                    )
    if pred and not gt:
        flags.append("FALSE_POS: detection on image with no kept labels in split")
    return flags


def run_sanity_check(
    weights: Path,
    dataset_root: Path,
    output_dir: Path,
    conf: float,
    samples_per_class: int,
    splits: Sequence[str],
    device: str,
    save_annotated: bool,
) -> Dict[str, object]:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("pip install ultralytics") from exc

    if not weights.is_file():
        raise FileNotFoundError(f"Weights not found: {weights}")

    model = YOLO(str(weights))
    samples = collect_samples(dataset_root, splits, samples_per_class)
    if not samples:
        raise FileNotFoundError(f"No labeled samples found under {dataset_root}")

    output_dir.mkdir(parents=True, exist_ok=True)
    results: List[SampleResult] = []

    for image_path, label_path, split, gt in samples:
        yolo_results = model.predict(
            source=str(image_path),
            conf=conf,
            device=device,
            verbose=False,
        )
        detections, img_w, img_h = _parse_yolo_results(yolo_results, conf)
        cv_response = build_cv_response(detections, img_w, img_h)
        pred = {d.defect_class for d in detections}
        severity = cv_response.severity_tier.value if cv_response.severity_tier else None
        flags = _demo_flags(gt, pred, severity, detections, conf, img_w, img_h)

        if save_annotated and yolo_results:
            annotated = yolo_results[0].plot()
            out_name = f"{split}_{image_path.stem}_sanity.jpg"
            try:
                import cv2

                cv2.imwrite(str(output_dir / out_name), annotated)
            except Exception:
                pass

        results.append(
            SampleResult(
                image=image_path,
                split=split,
                gt_classes=gt,
                pred_classes=pred,
                detections=detections,
                severity_tier=severity,
                primary_defect=cv_response.primary_defect,
                demo_flags=flags,
            )
        )

    per_class_gt = Counter()
    per_class_hit = Counter()
    all_flags: Counter[str] = Counter()
    for r in results:
        for cls in r.gt_classes:
            per_class_gt[cls] += 1
            if cls in r.pred_classes:
                per_class_hit[cls] += 1
        for f in r.demo_flags:
            all_flags[f.split(":")[0]] += 1

    report = {
        "weights": str(weights.resolve()),
        "dataset": str(dataset_root.resolve()),
        "conf": conf,
        "samples": len(results),
        "per_class_recall_on_samples": {
            cls: round(per_class_hit[cls] / per_class_gt[cls], 3) if per_class_gt[cls] else None
            for cls in CLASS_NAMES
        },
        "demo_flag_counts": dict(all_flags),
        "details": [
            {
                "image": str(r.image),
                "split": r.split,
                "gt": sorted(r.gt_classes),
                "pred": sorted(r.pred_classes),
                "severity_tier": r.severity_tier,
                "primary_defect": r.primary_defect,
                "detections": [
                    {"class": d.defect_class, "conf": d.confidence, "bbox": d.bbox}
                    for d in r.detections
                ],
                "flags": r.demo_flags,
            }
            for r in results
        ],
    }

    report_path = output_dir / "sanity_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    _print_report(results, per_class_gt, per_class_hit, all_flags, report_path)
    return report


def _print_report(
    results: List[SampleResult],
    per_class_gt: Counter,
    per_class_hit: Counter,
    all_flags: Counter,
    report_path: Path,
) -> None:
    print("=" * 72)
    print("TALAP CV SANITY CHECK (demo-oriented, not benchmark mAP)")
    print("=" * 72)
    print(f"Samples: {len(results)}  |  Report: {report_path}")
    print()
    print("Per-class recall on curated val/test samples (eyeball these, not mAP):")
    for cls in CLASS_NAMES:
        gt_n = per_class_gt[cls]
        hit = per_class_hit[cls]
        if gt_n == 0:
            print(f"  {cls:22s}  (no samples in this run)")
        else:
            print(f"  {cls:22s}  {hit}/{gt_n}  ({100*hit/gt_n:.0f}%)")
    print()
    if all_flags:
        print("Demo risk flags (aggregate):")
        for flag, count in all_flags.most_common():
            print(f"  {flag}: {count}")
    else:
        print("No demo risk flags on sampled images.")
    print()
    print("Per-image summary:")
    for r in results:
        flag_str = f"  ⚠ {', '.join(r.demo_flags)}" if r.demo_flags else ""
        print(
            f"  [{r.split}] {r.image.name}: "
            f"gt={sorted(r.gt_classes)} pred={sorted(r.pred_classes)} "
            f"tier={r.severity_tier}{flag_str}"
        )
    print("=" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-training CV sanity check for demo readiness")
    default_weights = _BACKEND / "runs/detect/training/runs/single_stage/weights/best.pt"
    fallback_weights = _BACKEND / "training/weights/best.pt"
    parser.add_argument(
        "--weights",
        type=Path,
        default=default_weights if default_weights.is_file() else fallback_weights,
    )
    parser.add_argument("--data", type=Path, default=_BACKEND / "training/dataset_v1/data.yaml")
    parser.add_argument("--output", type=Path, default=_BACKEND / "training/sanity_output")
    parser.add_argument("--conf", type=float, default=0.4, help="Production CV_CONFIDENCE_THRESHOLD")
    parser.add_argument("--samples-per-class", type=int, default=5)
    parser.add_argument("--splits", type=str, default="val,test", help="Comma-separated splits to sample")
    parser.add_argument("--device", type=str, default="mps")
    parser.add_argument("--no-images", action="store_true", help="Skip saving annotated JPGs")
    args = parser.parse_args()

    dataset_root = args.data.parent if args.data.name == "data.yaml" else args.data
    run_sanity_check(
        weights=args.weights,
        dataset_root=dataset_root,
        output_dir=args.output,
        conf=args.conf,
        samples_per_class=args.samples_per_class,
        splits=[s.strip() for s in args.splits.split(",") if s.strip()],
        device=args.device,
        save_annotated=not args.no_images,
    )


if __name__ == "__main__":
    main()
