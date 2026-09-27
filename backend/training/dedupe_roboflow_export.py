"""
Deduplicate a Roboflow YOLO export by collapsing pre-baked augmentation copies.

Roboflow Universe exports often save each augmented variant as a separate static file
sharing a filename stem like ``{source}_jpg.rf.{hash}.jpg``. This script groups those
files, keeps one representative per group, and writes a deduplicated dataset copy.

Usage (from talap/backend):
    python training/dedupe_roboflow_export.py \\
        --input /Users/darkhan/data/roboflow_manhole \\
        --output /Users/darkhan/data/roboflow_manhole_dedup
"""

from __future__ import annotations

import argparse
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
ROBOFLOW_STEM_RE = re.compile(r"^(.+)\.rf\.[a-f0-9]{32}$", re.IGNORECASE)
SPLITS = ("train", "valid", "test")


@dataclass
class ImageRecord:
    split: str
    image_path: Path
    label_path: Path
    base_id: str
    group_key: str


@dataclass
class DedupeSummary:
    files_in: int = 0
    unique_groups: int = 0
    files_kept: int = 0
    files_dropped: int = 0
    grouping_method: Counter[str] = field(default_factory=Counter)
    example_groups: List[Tuple[str, List[str], str]] = field(default_factory=list)


def _label_for_image(image_path: Path) -> Path:
    return image_path.parent.parent / "labels" / f"{image_path.stem}.txt"


def _roboflow_base_id(stem: str) -> Optional[str]:
    match = ROBOFLOW_STEM_RE.match(stem)
    if not match:
        return None
    return match.group(1)


def _collect_records(input_root: Path) -> List[ImageRecord]:
    records: List[ImageRecord] = []
    for split in SPLITS:
        images_dir = input_root / split / "images"
        if not images_dir.is_dir():
            continue
        for image_path in sorted(images_dir.iterdir()):
            if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            label_path = _label_for_image(image_path)
            if not label_path.is_file():
                raise FileNotFoundError(
                    f"Missing label for image {image_path} (expected {label_path})"
                )
            base_id = _roboflow_base_id(image_path.stem)
            group_key = base_id if base_id is not None else f"__unique__:{image_path.name}"
            records.append(
                ImageRecord(
                    split=split,
                    image_path=image_path,
                    label_path=label_path,
                    base_id=base_id or image_path.stem,
                    group_key=group_key,
                )
            )
    return records


def _pick_representative(members: Sequence[ImageRecord]) -> ImageRecord:
    """Keep the first file by (split, filename) sort — stable and reproducible."""
    return sorted(members, key=lambda r: (r.split, r.image_path.name))[0]


def _group_with_imagehash(
    records: Sequence[ImageRecord],
    hash_size: int = 8,
) -> Dict[str, List[ImageRecord]]:
    try:
        import imagehash
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "imagehash and Pillow are required for perceptual-hash fallback. "
            "Install with: pip install imagehash Pillow"
        ) from exc

    groups: Dict[str, List[ImageRecord]] = {}
    hashes: List[Tuple[ImageRecord, imagehash.ImageHash]] = []
    for record in records:
        with Image.open(record.image_path) as img:
            digest = imagehash.phash(img, hash_size=hash_size)
        hashes.append((record, digest))

    assigned: Dict[int, str] = {}
    next_group = 0
    for idx, (record, digest) in enumerate(hashes):
        matched_key: Optional[str] = None
        for prior_idx, prior_key in assigned.items():
            prior_digest = hashes[prior_idx][1]
            if digest - prior_digest <= 2:
                matched_key = prior_key
                break
        if matched_key is None:
            matched_key = f"phash:{next_group}"
            next_group += 1
        assigned[idx] = matched_key
        groups.setdefault(matched_key, []).append(record)
    return groups


def dedupe_roboflow_export(
    input_root: Path,
    output_root: Path,
    example_limit: int = 5,
) -> DedupeSummary:
    input_root = input_root.resolve()
    output_root = output_root.resolve()
    records = _collect_records(input_root)
    summary = DedupeSummary(files_in=len(records))

    roboflow_groups: Dict[str, List[ImageRecord]] = {}
    unmatched: List[ImageRecord] = []
    for record in records:
        if record.group_key.startswith("__unique__:"):
            unmatched.append(record)
        else:
            roboflow_groups.setdefault(record.group_key, []).append(record)

    summary.grouping_method["roboflow_stem"] = len(roboflow_groups)
    grouped: Dict[str, List[ImageRecord]] = dict(roboflow_groups)

    if unmatched:
        phash_groups = _group_with_imagehash(unmatched)
        grouped.update(phash_groups)
        summary.grouping_method["perceptual_hash"] = len(phash_groups)

    summary.unique_groups = len(grouped)
    kept: List[ImageRecord] = []
    dropped_examples: List[Tuple[str, List[str], str]] = []

    for group_key, members in sorted(grouped.items()):
        representative = _pick_representative(members)
        kept.append(representative)
        if len(members) > 1 and len(dropped_examples) < example_limit:
            dropped_examples.append(
                (
                    group_key,
                    [m.image_path.name for m in members],
                    representative.image_path.name,
                )
            )

    summary.files_kept = len(kept)
    summary.files_dropped = summary.files_in - summary.files_kept
    summary.example_groups = dropped_examples

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    yaml_src = input_root / "data.yaml"
    if yaml_src.is_file():
        shutil.copy2(yaml_src, output_root / "data.yaml")
    else:
        raise FileNotFoundError(f"Expected data.yaml in {input_root}")

    for record in kept:
        out_images = output_root / record.split / "images"
        out_labels = output_root / record.split / "labels"
        out_images.mkdir(parents=True, exist_ok=True)
        out_labels.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record.image_path, out_images / record.image_path.name)
        shutil.copy2(record.label_path, out_labels / record.label_path.name)

    return summary


def _print_summary(summary: DedupeSummary) -> None:
    print("Roboflow export deduplication summary")
    print(f"  Files in:        {summary.files_in}")
    print(f"  Unique groups:   {summary.unique_groups}")
    print(f"  Files kept:      {summary.files_kept}")
    print(f"  Files dropped:   {summary.files_dropped}")
    if summary.grouping_method:
        methods = ", ".join(f"{k}={v}" for k, v in sorted(summary.grouping_method.items()))
        print(f"  Grouping method: {methods}")
    if summary.example_groups:
        print("  Example duplicate groups (kept file marked with *):")
        for group_key, names, kept_name in summary.example_groups:
            print(f"    [{group_key}]")
            for name in names:
                marker = "*" if name == kept_name else " "
                print(f"      {marker} {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate Roboflow YOLO export augmentations")
    parser.add_argument("--input", type=Path, required=True, help="Roboflow export root")
    parser.add_argument("--output", type=Path, required=True, help="Deduped output root")
    parser.add_argument(
        "--examples",
        type=int,
        default=5,
        help="Number of example duplicate groups to print",
    )
    args = parser.parse_args()

    summary = dedupe_roboflow_export(args.input, args.output, example_limit=args.examples)
    _print_summary(summary)
    print(f"Wrote deduplicated dataset to {args.output.resolve()}")


if __name__ == "__main__":
    main()
