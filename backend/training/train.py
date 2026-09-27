from __future__ import annotations
"""
Two-stage YOLO26 fine-tuning for Talap road defect detection.

Run from talap/backend:
    python training/train.py --data training/dataset/data.yaml
    python training/train.py --data training/dataset/data.yaml --no-freeze
    python training/train.py --data training/dataset/data.yaml --baseline-only
"""

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

try:
    from ultralytics import YOLO
except ImportError as exc:
    raise SystemExit("pip install -r training/requirements.txt") from exc

WEIGHTS_DIR = Path("training/weights")
BEST_WEIGHTS = WEIGHTS_DIR / "best.pt"
RUNS_LOG = Path("training/runs_log.json")
PRETRAINED_CANDIDATES = ("yolo26s.pt", "yolo11s.pt", "yolov8s.pt")


@dataclass
class LoadedModelInfo:
    model: "YOLO"
    weights_name: str
    architecture: str
    parameters: int


def _describe_model(model: "YOLO", weights_name: str) -> LoadedModelInfo:
    det_model = model.model
    yaml_cfg = getattr(det_model, "yaml", None) or {}
    yaml_file = yaml_cfg.get("yaml_file", "unknown")
    scale = yaml_cfg.get("scale", "")
    arch_stem = Path(str(yaml_file)).stem if yaml_file != "unknown" else type(det_model).__name__
    architecture = f"{arch_stem}{scale}" if scale else arch_stem
    parameters = sum(int(p.numel()) for p in det_model.parameters())
    return LoadedModelInfo(
        model=model,
        weights_name=weights_name,
        architecture=architecture,
        parameters=parameters,
    )


def _load_pretrained() -> LoadedModelInfo:
    last_err: Exception | None = None
    for name in PRETRAINED_CANDIDATES:
        try:
            model = YOLO(name)
            info = _describe_model(model, name)
            print(
                f"Loaded pretrained backbone: {info.weights_name} "
                f"({info.architecture}, {info.parameters:,} parameters)"
            )
            return info
        except Exception as exc:
            last_err = exc
    raise RuntimeError(f"Could not load any pretrained model: {PRETRAINED_CANDIDATES}") from last_err


def _load_model_from_checkpoint(weights_path: Path) -> LoadedModelInfo:
    model = YOLO(str(weights_path))
    info = _describe_model(model, str(weights_path))
    print(
        f"Loaded checkpoint: {info.weights_name} "
        f"({info.architecture}, {info.parameters:,} parameters)"
    )
    return info


def _checkpoint_log_dict(info: LoadedModelInfo) -> Dict[str, Any]:
    return {
        "weights": info.weights_name,
        "architecture": info.architecture,
        "parameters": info.parameters,
    }


def _log_metrics(stage: str, results) -> Dict[str, Any]:
    metrics = getattr(results, "results_dict", None) or {}
    box = getattr(results, "box", None)
    summary = {
        "map50": metrics.get("metrics/mAP50(B)") or metrics.get("metrics/mAP50") or getattr(box, "map50", None),
        "map50_95": metrics.get("metrics/mAP50-95(B)") or metrics.get("metrics/mAP50-95") or getattr(box, "map", None),
    }
    print(f"[{stage}] mAP50={summary['map50']} mAP50-95={summary['map50_95']}")
    return summary


def _find_best_pt(project: Path, stage_name: str) -> Path | None:
    candidates = [
        project / stage_name / "weights" / "best.pt",
        Path("runs/detect") / project / stage_name / "weights" / "best.pt",
        Path.cwd() / "runs" / "detect" / project / stage_name / "weights" / "best.pt",
    ]
    for path in sorted(Path.cwd().glob(f"**/{stage_name}/weights/best.pt")):
        candidates.append(path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def append_runs_log(entry: Dict[str, Any]) -> None:
    RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    history: list = []
    if RUNS_LOG.is_file():
        try:
            history = json.loads(RUNS_LOG.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except json.JSONDecodeError:
            history = []
    history.append(entry)
    RUNS_LOG.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Appended run log entry to {RUNS_LOG.resolve()}")


def run_baseline_eval(
    data_yaml: Path,
    imgsz: int,
    device: str,
    seed: int,
) -> Tuple[Dict[str, Any], LoadedModelInfo]:
    """Zero-shot pretrained checkpoint on held-out test split."""
    from training.eval import evaluate_and_save

    loaded = _load_pretrained()
    metrics = evaluate_and_save(
        model=loaded.model,
        weights_label=loaded.weights_name,
        data_yaml=data_yaml,
        split="test",
        imgsz=imgsz,
        device=device,
        seed=seed,
        run_tag="baseline_pretrained",
    )
    return metrics, loaded


def train(
    data_yaml: Path,
    kz_data_yaml: Optional[Path] = None,
    epochs: int = 50,
    batch: int = 16,
    imgsz: int = 640,
    device: str = "cpu",
    project: Path = Path("training/runs"),
    seed: int = 42,
    no_freeze: bool = False,
) -> Path:
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)

    loaded = _load_pretrained()
    model = loaded.model
    run_metrics: Dict[str, Any] = {}
    checkpoint_log: Dict[str, Any] = {
        "pretrained": _checkpoint_log_dict(loaded),
        "stages": {},
    }
    mode = "no_freeze" if no_freeze else "two_stage"

    if no_freeze:
        print(f"Single-stage fine-tune: {epochs} epochs on {data_yaml} (no backbone freeze)")
        checkpoint_log["stages"]["single_stage"] = {
            "input_weights": loaded.weights_name,
        }
        results = model.train(
            data=str(data_yaml),
            epochs=epochs,
            batch=batch,
            imgsz=imgsz,
            device=device,
            seed=seed,
            freeze=0,
            lr0=0.001,
            project=str(project),
            name="single_stage",
            exist_ok=True,
        )
        run_metrics["single_stage"] = _log_metrics("single_stage", results)
        best_stage = "single_stage"
        single_weights = _find_best_pt(project, best_stage)
        if single_weights is not None:
            checkpoint_log["stages"]["single_stage"]["output_weights"] = str(single_weights.resolve())
    else:
        stage1_data = kz_data_yaml if kz_data_yaml and kz_data_yaml.is_file() else data_yaml
        stage1_epochs = max(1, epochs // 3)
        print(f"Stage 1: {stage1_epochs} epochs on {stage1_data} (freeze=10, seed={seed})")
        checkpoint_log["stages"]["stage1"] = {
            "input_weights": loaded.weights_name,
        }
        results1 = model.train(
            data=str(stage1_data),
            epochs=stage1_epochs,
            batch=batch,
            imgsz=imgsz,
            device=device,
            seed=seed,
            freeze=10,
            project=str(project),
            name="stage1_kz",
            exist_ok=True,
        )
        run_metrics["stage1"] = _log_metrics("stage1", results1)
        stage1_weights = _find_best_pt(project, "stage1_kz")
        if stage1_weights is not None:
            checkpoint_log["stages"]["stage1"]["output_weights"] = str(stage1_weights.resolve())

        stage2_epochs = max(1, epochs - stage1_epochs)
        stage2_input = stage1_weights or loaded.weights_name
        print(f"Stage 2: {stage2_epochs} epochs on {data_yaml} (lr0=0.001, seed={seed})")
        checkpoint_log["stages"]["stage2"] = {
            "input_weights": str(stage2_input) if isinstance(stage2_input, Path) else stage2_input,
        }
        results2 = model.train(
            data=str(data_yaml),
            epochs=stage2_epochs,
            batch=batch,
            imgsz=imgsz,
            device=device,
            seed=seed,
            freeze=0,
            lr0=0.001,
            project=str(project),
            name="stage2_combined",
            exist_ok=True,
        )
        run_metrics["stage2"] = _log_metrics("stage2", results2)
        best_stage = "stage2_combined"
        stage2_weights = _find_best_pt(project, best_stage)
        if stage2_weights is not None:
            checkpoint_log["stages"]["stage2"]["output_weights"] = str(stage2_weights.resolve())

    run_weights = _find_best_pt(project, best_stage) or _find_best_pt(project, "stage1_kz")
    if run_weights is None:
        raise FileNotFoundError("Training finished but no best.pt weights were produced")

    shutil.copy2(run_weights, BEST_WEIGHTS)
    print(f"Saved best weights to {BEST_WEIGHTS.resolve()}")

    append_runs_log(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "epochs": epochs,
            "seed": seed,
            "freeze": not no_freeze,
            "data_yaml": str(data_yaml.resolve()),
            "kz_data_yaml": str(kz_data_yaml.resolve()) if kz_data_yaml else None,
            "device": device,
            "imgsz": imgsz,
            "batch": batch,
            "weights_out": str(BEST_WEIGHTS.resolve()),
            "checkpoints": checkpoint_log,
            "metrics": run_metrics,
        }
    )
    return BEST_WEIGHTS


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Fine-tune YOLO26 for Talap")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument(
        "--kz-data",
        type=Path,
        default=None,
        help="KZ-only data.yaml for stage 1 (default: auto-detect dataset/kz_only/data.yaml)",
    )
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument(
        "--no-freeze",
        action="store_true",
        help="Skip frozen stage-1; run full epoch budget as single-stage fine-tune",
    )
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="Skip training; evaluate raw pretrained checkpoint on test split",
    )
    args = parser.parse_args(argv)

    if args.baseline_only:
        metrics, loaded = run_baseline_eval(
            data_yaml=args.data,
            imgsz=args.imgsz,
            device=args.device,
            seed=args.seed,
        )
        append_runs_log(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "baseline_only",
                "epochs": 0,
                "seed": args.seed,
                "freeze": False,
                "data_yaml": str(args.data.resolve()),
                "device": args.device,
                "imgsz": args.imgsz,
                "checkpoints": {"pretrained": _checkpoint_log_dict(loaded)},
                "metrics": metrics,
            }
        )
        return

    kz_yaml = args.kz_data
    if kz_yaml is None:
        auto = args.data.parent / "kz_only" / "data.yaml"
        if auto.is_file():
            kz_yaml = auto

    train(
        data_yaml=args.data,
        kz_data_yaml=kz_yaml,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device,
        seed=args.seed,
        no_freeze=args.no_freeze,
    )


if __name__ == "__main__":
    main()
