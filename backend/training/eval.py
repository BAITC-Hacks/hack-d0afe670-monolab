"""
Evaluate Talap YOLO weights on the held-out test split (default).

The test split must only be used for final reporting — never for training or
threshold tuning. Use --allow-val to evaluate on val (for debugging only).

Usage (from talap/backend):
    python training/eval.py --weights training/weights/best.pt --data training/dataset/data.yaml
    python training/eval.py --compare-to training/eval_output/metrics_latest.json
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

try:
    from ultralytics import YOLO
except ImportError as exc:
    raise SystemExit("pip install -r training/requirements.txt") from exc

from training.prepare_dataset import CLASS_NAMES

EVAL_OUTPUT_DIR = Path("training/eval_output")
METRICS_LATEST = EVAL_OUTPUT_DIR / "metrics_latest.json"


def _f1(precision: float, recall: float) -> float:
    if precision + recall <= 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _safe_index(values: Any, idx: int) -> Optional[float]:
    if values is None:
        return None
    try:
        val = values[idx]
        return float(val) if val is not None else None
    except (IndexError, TypeError, ValueError):
        return None


def _extract_per_class_metrics(results) -> List[Dict[str, Any]]:
    box = getattr(results, "box", None)
    if box is None:
        return []

    per_class: List[Dict[str, Any]] = []
    for idx, name in enumerate(CLASS_NAMES):
        p = _safe_index(getattr(box, "p", None), idx)
        r = _safe_index(getattr(box, "r", None), idx)
        ap50 = _safe_index(getattr(box, "ap50", None), idx)
        per_class.append(
            {
                "class": name,
                "precision": p,
                "recall": r,
                "f1": _f1(p or 0.0, r or 0.0) if p is not None and r is not None else None,
                "ap50": ap50,
            }
        )
    return per_class


def _save_confusion_matrix(results, output_dir: Path) -> Optional[Path]:
    cm = getattr(results, "confusion_matrix", None)
    if cm is None:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "confusion_matrix.png"

    if hasattr(cm, "plot"):
        try:
            cm.plot()
        except Exception:
            pass

    # Ultralytics saves to cwd; also try direct matrix plot paths
    for candidate in [
        Path("confusion_matrix.png"),
        Path("confusion_matrix_normalized.png"),
    ]:
        if candidate.is_file():
            shutil.copy2(candidate, dest)
            return dest

    if hasattr(cm, "matrix"):
        try:
            import matplotlib.pyplot as plt
            import numpy as np

            matrix = np.array(cm.matrix)
            fig, ax = plt.subplots(figsize=(8, 8))
            ax.imshow(matrix, interpolation="nearest")
            ax.set_title("Confusion Matrix")
            labels = list(getattr(cm, "names", CLASS_NAMES))
            ax.set_xticks(range(len(labels)))
            ax.set_yticks(range(len(labels)))
            ax.set_xticklabels(labels, rotation=45, ha="right")
            ax.set_yticklabels(labels)
            fig.tight_layout()
            fig.savefig(dest, dpi=150)
            plt.close(fig)
            return dest
        except Exception:
            return None
    return None


def evaluate_and_save(
    *,
    model: Optional[YOLO] = None,
    weights: Optional[Path] = None,
    weights_label: Optional[str] = None,
    data_yaml: Path,
    split: str = "test",
    imgsz: int = 640,
    device: str = "cpu",
    conf: float = 0.25,
    seed: int = 42,
    run_tag: str = "eval",
    output_dir: Path = EVAL_OUTPUT_DIR,
) -> Dict[str, Any]:
    if model is None:
        if weights is None or not weights.is_file():
            raise FileNotFoundError(f"Weights not found: {weights}")
        model = YOLO(str(weights))
        weights_label = str(weights.resolve())

    if not data_yaml.is_file():
        raise FileNotFoundError(f"data.yaml not found: {data_yaml}")

    results = model.val(
        data=str(data_yaml),
        split=split,
        imgsz=imgsz,
        device=device,
        conf=conf,
        seed=seed,
        verbose=False,
    )

    metrics_dict = getattr(results, "results_dict", None) or {}
    box = getattr(results, "box", None)
    overall = {
        "map50": metrics_dict.get("metrics/mAP50(B)") or metrics_dict.get("metrics/mAP50") or getattr(box, "map50", None),
        "map50_95": metrics_dict.get("metrics/mAP50-95(B)") or metrics_dict.get("metrics/mAP50-95") or getattr(box, "map", None),
        "precision": metrics_dict.get("metrics/precision(B)") or getattr(box, "mp", None),
        "recall": metrics_dict.get("metrics/recall(B)") or getattr(box, "mr", None),
    }
    per_class = _extract_per_class_metrics(results)

    output_dir.mkdir(parents=True, exist_ok=True)
    cm_path = _save_confusion_matrix(results, output_dir)

    payload: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_tag": run_tag,
        "weights": weights_label,
        "data_yaml": str(data_yaml.resolve()),
        "split": split,
        "seed": seed,
        "imgsz": imgsz,
        "device": device,
        "conf": conf,
        "overall": overall,
        "per_class": per_class,
        "confusion_matrix": str(cm_path.resolve()) if cm_path else None,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stamped_path = output_dir / f"metrics_{stamp}.json"
    stamped_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    METRICS_LATEST.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    _print_metrics_report(payload)
    print(f"\nSaved metrics: {stamped_path.resolve()}")
    print(f"Latest metrics:  {METRICS_LATEST.resolve()}")
    if cm_path:
        print(f"Confusion matrix: {cm_path.resolve()}")

    return payload


def _print_metrics_report(payload: Dict[str, Any]) -> None:
    overall = payload["overall"]
    print("=== Talap CV evaluation ===")
    print(f"weights: {payload['weights']}")
    print(f"data:    {payload['data_yaml']}")
    print(f"split:   {payload['split']}  (seed={payload['seed']})")
    print(f"  mAP50:     {overall.get('map50')}")
    print(f"  mAP50-95:  {overall.get('map50_95')}")
    print(f"  precision: {overall.get('precision')}")
    print(f"  recall:    {overall.get('recall')}")
    print("\nPer-class metrics:")
    print(f"  {'class':<22} {'P':>8} {'R':>8} {'F1':>8} {'AP50':>8}")
    for row in payload["per_class"]:
        p = row["precision"]
        r = row["recall"]
        f1 = row["f1"]
        ap50 = row["ap50"]
        print(
            f"  {row['class']:<22} "
            f"{p if p is not None else '—':>8} "
            f"{r if r is not None else '—':>8} "
            f"{f1 if f1 is not None else '—':>8} "
            f"{ap50 if ap50 is not None else '—':>8}"
        )


def print_compare_delta(current: Dict[str, Any], baseline: Dict[str, Any]) -> None:
    print("\n=== Comparison (current vs baseline) ===")
    print(f"  current:  {current.get('weights')} [{current.get('run_tag')}]")
    print(f"  baseline: {baseline.get('weights')} [{baseline.get('run_tag')}]")
    print(f"  {'metric':<22} {'current':>10} {'baseline':>10} {'delta':>10}")

    for key in ("map50", "map50_95", "precision", "recall"):
        cur = current.get("overall", {}).get(key)
        base = baseline.get("overall", {}).get(key)
        if cur is None or base is None:
            continue
        delta = cur - base
        sign = "+" if delta >= 0 else ""
        print(f"  {key:<22} {cur:10.4f} {base:10.4f} {sign}{delta:9.4f}")

    print(f"\n  {'class':<22} {'ΔAP50':>10}")
    base_by_class = {r["class"]: r for r in baseline.get("per_class", [])}
    for row in current.get("per_class", []):
        cls = row["class"]
        cur_ap = row.get("ap50")
        base_ap = base_by_class.get(cls, {}).get("ap50")
        if cur_ap is None or base_ap is None:
            continue
        delta = cur_ap - base_ap
        sign = "+" if delta >= 0 else ""
        print(f"  {cls:<22} {sign}{delta:9.4f}")


def evaluate(
    weights: Path,
    data_yaml: Path,
    split: str = "test",
    imgsz: int = 640,
    device: str = "cpu",
    conf: float = 0.25,
    seed: int = 42,
    compare_to: Optional[Path] = None,
) -> Dict[str, Any]:
    payload = evaluate_and_save(
        weights=weights,
        data_yaml=data_yaml,
        split=split,
        imgsz=imgsz,
        device=device,
        conf=conf,
        seed=seed,
    )
    if compare_to is not None:
        if not compare_to.is_file():
            raise FileNotFoundError(f"Comparison metrics not found: {compare_to}")
        baseline = json.loads(compare_to.read_text(encoding="utf-8"))
        print_compare_delta(payload, baseline)
    return payload


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate Talap YOLO weights (test split by default)")
    parser.add_argument("--weights", type=Path, default=Path("training/weights/best.pt"))
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--split", choices=("val", "test"), default="test")
    parser.add_argument(
        "--allow-val",
        action="store_true",
        help="Required when --split val (prevents accidental val-as-final reporting)",
    )
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--compare-to",
        type=Path,
        default=None,
        help="Path to a previous metrics JSON for side-by-side delta table",
    )
    args = parser.parse_args(argv)

    if args.split == "val" and not args.allow_val:
        parser.error("Evaluating on val requires --allow-val (use --split test for final results)")

    evaluate(
        weights=args.weights,
        data_yaml=args.data,
        split=args.split,
        imgsz=args.imgsz,
        device=args.device,
        conf=args.conf,
        seed=args.seed,
        compare_to=args.compare_to,
    )


if __name__ == "__main__":
    main()
