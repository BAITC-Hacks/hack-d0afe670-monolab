from __future__ import annotations
"""
Prepare RDD2022 (+ optional KZ custom photos + external YOLO datasets) in YOLO format.

The held-out **test** split is created here but must NEVER be used for training,
hyperparameter tuning, or threshold selection — only for final evaluation via
``training/eval.py``.

Usage (from talap/backend):
    python training/prepare_dataset.py --rdd-root /path/to/RDD2022 --output training/dataset
    python training/prepare_dataset.py \\
        --extra-dataset /path/to/roboflow_export:manhole=sunken_manhole,pothole=pothole \\
        --output training/dataset
"""

import argparse
import ast
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from training.balance_utils import (
    StemMeta,
    apply_subgroup_balance,
    build_subgroup_stats,
    infer_subgroup_from_image_stem,
    print_balance_report,
)
from training.split_utils import (
    SPLIT_NAMES,
    resolve_split_ratios,
    stratified_three_way_split,
)

CLASS_NAMES: List[str] = [
    "pothole",
    "crack_longitudinal",
    "crack_alligator",
    "sunken_manhole",
    "rutting",
]
CLASS_TO_ID: Dict[str, int] = {name: idx for idx, name in enumerate(CLASS_NAMES)}

RDD_DAMAGE_MAP: Dict[str, str] = {
    "D00": "crack_longitudinal",
    "D10": "crack_longitudinal",
    "D20": "crack_alligator",
    "D40": "pothole",
}

DEFAULT_SPLIT_RATIOS_STR = "0.70,0.15,0.15"
DEFAULT_SEED = 42

# Legacy defaults (no test split when these are explicitly passed)
DEFAULT_VAL_RATIO = 0.15
DEFAULT_TRAIN_SPLIT_RATIO = 0.85

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

YoloLabel = Tuple[int, float, float, float, float]
SplitCounts = Dict[str, int]


@dataclass
class SourceSplitCounts:
    source: str
    train: int = 0
    val: int = 0
    test: int = 0
    subgroup_stats: List = field(default_factory=list)

    def as_dict(self) -> SplitCounts:
        return {"train": self.train, "val": self.val, "test": self.test}


@dataclass
class ExternalMergeSummary:
    dataset_name: str
    total_images: int
    kept_images: int
    skipped_empty: int
    train_count: int
    val_count: int
    test_count: int
    class_distribution: Dict[str, int] = field(default_factory=dict)
    subgroup_stats: List = field(default_factory=list)


def _primary_class_id(labels: Sequence[YoloLabel]) -> int:
    if not labels:
        return -1
    return Counter(cid for cid, *_ in labels).most_common(1)[0][0]


def _parse_rdd_xml(xml_path: Path) -> Tuple[int, int, List[YoloLabel]]:
    root = ET.parse(xml_path).getroot()
    size = root.find("size")
    if size is None:
        return 0, 0, []
    width = int(size.findtext("width", "0"))
    height = int(size.findtext("height", "0"))
    if width <= 0 or height <= 0:
        return 0, 0, []

    labels: List[YoloLabel] = []
    for obj in root.findall("object"):
        code = (obj.findtext("name") or "").strip()
        mapped = RDD_DAMAGE_MAP.get(code)
        if mapped is None:
            continue
        class_id = CLASS_TO_ID[mapped]
        bbox = obj.find("bndbox")
        if bbox is None:
            continue
        xmin = float(bbox.findtext("xmin", "0"))
        ymin = float(bbox.findtext("ymin", "0"))
        xmax = float(bbox.findtext("xmax", "0"))
        ymax = float(bbox.findtext("ymax", "0"))
        x_center = ((xmin + xmax) / 2.0) / width
        y_center = ((ymin + ymax) / 2.0) / height
        box_w = (xmax - xmin) / width
        box_h = (ymax - ymin) / height
        labels.append((class_id, x_center, y_center, box_w, box_h))
    return width, height, labels


def _write_yolo_label(path: Path, labels: Sequence[YoloLabel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{cid} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}" for cid, xc, yc, bw, bh in labels]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _read_yolo_label(path: Path) -> List[YoloLabel]:
    labels: List[YoloLabel] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            continue
        class_id = int(parts[0])
        coords = tuple(float(v) for v in parts[1:])
        labels.append((class_id, coords[0], coords[1], coords[2], coords[3]))
    return labels


def _normalize_country_filter(countries: Optional[Sequence[str]]) -> Optional[set[str]]:
    if not countries:
        return None
    normalized = {name.strip() for name in countries if name.strip()}
    return normalized or None


def _discover_rdd_pairs(
    rdd_root: Path,
    countries: Optional[Sequence[str]] = None,
) -> List[Tuple[Path, Path]]:
    pairs: List[Tuple[Path, Path]] = []
    country_filter = _normalize_country_filter(countries)
    for country_dir in sorted(rdd_root.iterdir()):
        if not country_dir.is_dir():
            continue
        if country_filter is not None and country_dir.name not in country_filter:
            continue
        images_dir = country_dir / "train" / "images"
        xml_dirs = [
            country_dir / "train" / "annotations" / "xmls",
            country_dir / "train" / "annotations",
        ]
        xml_dir = next((d for d in xml_dirs if d.is_dir()), None)
        if images_dir.is_dir() and xml_dir is not None:
            for img in sorted(images_dir.glob("*.jpg")):
                xml = xml_dir / f"{img.stem}.xml"
                if xml.is_file():
                    pairs.append((img, xml))
    return pairs


def _copy_pair(
    image: Path,
    labels: Sequence[YoloLabel],
    images_out: Path,
    labels_out: Path,
    stem: str,
) -> None:
    images_out.mkdir(parents=True, exist_ok=True)
    labels_out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image, images_out / f"{stem}.jpg")
    _write_yolo_label(labels_out / f"{stem}.txt", labels)


def _append_image_label_pair(
    image: Path,
    labels: Sequence[YoloLabel],
    output_dir: Path,
    split: str,
    stem: str,
) -> None:
    images_out = output_dir / "images" / split
    labels_out = output_dir / "labels" / split
    images_out.mkdir(parents=True, exist_ok=True)
    labels_out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image, images_out / f"{stem}{image.suffix.lower()}")
    _write_yolo_label(labels_out / f"{stem}.txt", labels)


def _write_split_items(
    output_dir: Path,
    split_items: Dict[str, Sequence[Tuple[Path, Sequence[YoloLabel], str]]],
) -> SplitCounts:
    counts = {"train": 0, "val": 0, "test": 0}
    for split_name, items in split_items.items():
        for image, labels, stem in items:
            _append_image_label_pair(image, labels, output_dir, split_name, stem)
            counts[split_name] += 1
    return counts


def prepare_rdd2022(
    rdd_root: Path,
    output_dir: Path,
    split_ratios: Tuple[float, float, float],
    seed: int = DEFAULT_SEED,
    countries: Optional[Sequence[str]] = None,
    stem_meta: Optional[StemMeta] = None,
    balance_strategy: str = "none",
    balance_sources: Optional[Sequence[str]] = None,
    balance_target: Optional[int] = None,
) -> SourceSplitCounts:
    pairs = _discover_rdd_pairs(rdd_root, countries=countries)
    if not pairs:
        raise FileNotFoundError(
            f"No RDD2022 train image/xml pairs under {rdd_root}. "
            "Expected Country/train/images + Country/train/annotations/xmls"
        )

    valid_items: List[Tuple[Path, List[YoloLabel], str]] = []
    for image, xml in pairs:
        _, _, labels = _parse_rdd_xml(xml)
        if not labels:
            continue
        stem = f"rdd_{image.stem}"
        valid_items.append((image, labels, stem))
        if stem_meta is not None:
            country = image.parent.parent.parent.name
            stem_meta[stem] = ("RDD2022", country)

    source_name = "RDD2022"
    if countries:
        source_name = f"RDD2022 ({', '.join(sorted(_normalize_country_filter(countries) or []))})"

    train, val, test = stratified_three_way_split(
        valid_items,
        stratify_key=lambda item: _primary_class_id(item[1]),
        ratios=split_ratios,
        seed=seed,
    )
    balance_sources_set = set(balance_sources or [])
    if balance_strategy != "none" and source_name in balance_sources_set and stem_meta is not None:
        train_stats = build_subgroup_stats(train, stem_meta)
        default_target = max((s.images for s in train_stats), default=0)
        target = balance_target or default_target
        train, balance_logs = apply_subgroup_balance(
            train, stem_meta, source_name, balance_strategy, target, seed=seed + 100
        )
        for line in balance_logs:
            print(line)

    subgroup_stats = (
        build_subgroup_stats(valid_items, stem_meta) if stem_meta is not None else []
    )

    counts = _write_split_items(
        output_dir,
        {"train": train, "val": val, "test": test},
    )
    return SourceSplitCounts(source=source_name, subgroup_stats=subgroup_stats, **counts)


def merge_kz_photos(
    kz_dir: Path,
    output_dir: Path,
    split_ratios: Tuple[float, float, float],
    seed: int = DEFAULT_SEED,
) -> SourceSplitCounts:
    images = sorted(
        list(kz_dir.glob("images/*.jpg"))
        + list(kz_dir.glob("images/*.jpeg"))
        + list(kz_dir.glob("images/*.png"))
    )
    if not images:
        raise FileNotFoundError(f"No images found in {kz_dir / 'images'}")

    valid_items: List[Tuple[Path, List[YoloLabel], str]] = []
    for img in images:
        label_path = kz_dir / "labels" / f"{img.stem}.txt"
        if not label_path.is_file():
            continue
        labels = _read_yolo_label(label_path)
        if not labels:
            continue
        valid_items.append((img, labels, f"kz_{img.stem}"))

    train, val, test = stratified_three_way_split(
        valid_items,
        stratify_key=lambda item: _primary_class_id(item[1]),
        ratios=split_ratios,
        seed=seed + 1,
    )

    counts = {"train": 0, "val": 0, "test": 0}
    for split_name, split_items in (("train", train), ("val", val), ("test", test)):
        images_out = output_dir / "images" / split_name
        labels_out = output_dir / "labels" / split_name
        images_out.mkdir(parents=True, exist_ok=True)
        labels_out.mkdir(parents=True, exist_ok=True)
        for image, labels, stem in split_items:
            shutil.copy2(image, images_out / f"{stem}{image.suffix}")
            _write_yolo_label(labels_out / f"{stem}.txt", labels)
            counts[split_name] += 1

    return SourceSplitCounts(source="KZ", **counts)


def parse_class_map(class_map_str: str) -> Dict[str, str]:
    if not class_map_str.strip():
        raise ValueError("CLASS_MAP is empty")

    mapping: Dict[str, str] = {}
    for part in class_map_str.split(","):
        entry = part.strip()
        if not entry or "=" not in entry:
            raise ValueError(f"Invalid CLASS_MAP entry: {entry!r}")
        external_name, target_name = entry.split("=", 1)
        external_name = external_name.strip()
        target_name = target_name.strip()
        if not external_name or not target_name:
            raise ValueError(f"Invalid CLASS_MAP entry: {entry!r}")
        if target_name not in CLASS_TO_ID:
            raise ValueError(
                f"CLASS_MAP target '{target_name}' is not in Talap taxonomy {CLASS_NAMES}"
            )
        mapping[external_name] = target_name
    return mapping


def parse_extra_dataset_arg(value: str) -> Tuple[Path, Dict[str, str]]:
    if ":" not in value:
        raise ValueError(f"Invalid --extra-dataset value {value!r}. Expected PATH:CLASS_MAP")
    path_str, class_map_str = value.split(":", 1)
    dataset_path = Path(path_str.strip())
    if not dataset_path.is_dir():
        raise FileNotFoundError(f"External dataset path not found: {dataset_path}")
    return dataset_path, parse_class_map(class_map_str)


def parse_explicit_drop_arg(value: str) -> Tuple[Path, set[str]]:
    if ":" not in value:
        raise ValueError(f"Invalid --explicit-drop value {value!r}. Expected PATH:CLASS1,CLASS2")
    path_str, names_str = value.split(":", 1)
    dataset_path = Path(path_str.strip()).resolve()
    if not dataset_path.is_dir():
        raise FileNotFoundError(f"External dataset path not found: {dataset_path}")
    names = {part.strip() for part in names_str.split(",") if part.strip()}
    if not names:
        raise ValueError(f"--explicit-drop for {dataset_path} must list at least one class name")
    return dataset_path, names


def resolve_explicit_drops_for_dataset(
    dataset_path: Path,
    explicit_drops_by_path: Mapping[Path, set[str]],
) -> set[str]:
    resolved = dataset_path.resolve()
    return set(explicit_drops_by_path.get(resolved, set()))


def _parse_names_block(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = ast.literal_eval(text)
        if not isinstance(parsed, list):
            raise ValueError("names list in data.yaml is not a list")
        return [str(name) for name in parsed]
    names: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            _, name = line.split(":", 1)
            names.append(name.strip().strip("'\""))
        else:
            names.append(line.strip().strip("'\""))
    return names


def parse_external_data_yaml(yaml_path: Path) -> Dict[int, str]:
    if not yaml_path.is_file():
        raise FileNotFoundError(f"External dataset data.yaml not found: {yaml_path}")

    try:
        text = yaml_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read external data.yaml at {yaml_path}: {exc}") from exc

    names: List[str] = []
    list_match = re.search(r"^names:\s*(\[.*\])\s*$", text, flags=re.MULTILINE)
    if list_match:
        names = _parse_names_block(list_match.group(1))
    else:
        block_match = re.search(r"^names:\s*\n((?:\s+.+\n?)+)", text, flags=re.MULTILINE)
        if block_match:
            names = _parse_names_block(block_match.group(1))

    if not names:
        raise ValueError(f"Could not parse class names from {yaml_path}")

    return {idx: name for idx, name in enumerate(names)}


def _discover_external_image_label_pairs(dataset_path: Path) -> List[Tuple[Path, Path]]:
    search_roots = [
        (dataset_path / "images", dataset_path / "labels"),
        (dataset_path / "train" / "images", dataset_path / "train" / "labels"),
        (dataset_path / "valid" / "images", dataset_path / "valid" / "labels"),
        (dataset_path / "val" / "images", dataset_path / "val" / "labels"),
    ]

    pairs: List[Tuple[Path, Path]] = []
    seen_stems: set[str] = set()
    for images_dir, labels_dir in search_roots:
        if not images_dir.is_dir() or not labels_dir.is_dir():
            continue
        for image in sorted(images_dir.iterdir()):
            if image.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            label = labels_dir / f"{image.stem}.txt"
            if not label.is_file():
                continue
            if image.stem in seen_stems:
                continue
            seen_stems.add(image.stem)
            pairs.append((image, label))
    return pairs


def warn_unmapped_classes(
    dataset_path: Path,
    class_map: Mapping[str, str],
    external_id_to_name: Mapping[int, str],
    explicit_drops: Optional[set[str]] = None,
) -> None:
    """
    Warn when external classes are neither mapped nor listed in --explicit-drop.

    Transverse-crack classes get an extra hint to match RDD_DAMAGE_MAP merge behavior.
    """
    drops = explicit_drops or set()
    all_external = set(external_id_to_name.values())
    unmapped = sorted((all_external - set(class_map.keys())) - drops)
    if not unmapped:
        return

    transverse_unmapped = [name for name in unmapped if "transverse" in name.lower()]
    other_unmapped = [name for name in unmapped if "transverse" not in name.lower()]

    if transverse_unmapped:
        print(
            f"WARNING: Dataset {dataset_path.name} defines transverse class(es) "
            f"{transverse_unmapped} that are NOT in CLASS_MAP or --explicit-drop — "
            f"those boxes will be dropped, not merged into crack_longitudinal. "
            f"To match --rdd-root / RDD_DAMAGE_MAP behavior, add e.g. "
            f"transverse_crack=crack_longitudinal to CLASS_MAP, or list the class "
            f"under --explicit-drop if exclusion is intentional."
        )
    if other_unmapped:
        print(
            f"WARNING: Dataset {dataset_path.name} defines class(es) {other_unmapped} "
            f"that are NOT in CLASS_MAP or --explicit-drop — those boxes will be dropped. "
            f"Add a CLASS_MAP entry or --explicit-drop {dataset_path}:"
            f"{','.join(other_unmapped)} if exclusion is intentional."
        )


def warn_unmapped_transverse_classes(
    dataset_path: Path,
    class_map: Mapping[str, str],
    external_id_to_name: Mapping[int, str],
    explicit_drops: Optional[set[str]] = None,
) -> None:
    """Backward-compatible alias; delegates to warn_unmapped_classes."""
    warn_unmapped_classes(dataset_path, class_map, external_id_to_name, explicit_drops)


def _validate_class_map_against_dataset(
    dataset_path: Path,
    class_map: Mapping[str, str],
    external_id_to_name: Mapping[int, str],
    explicit_drops: Optional[set[str]] = None,
) -> None:
    external_names = set(external_id_to_name.values())
    for external_name in class_map:
        if external_name not in external_names:
            available = ", ".join(sorted(external_names))
            raise ValueError(
                f"Dataset {dataset_path}: CLASS_MAP references unknown external class "
                f"'{external_name}'. Available classes: {available}"
            )
    drops = explicit_drops or set()
    unknown_drops = sorted(drops - external_names)
    if unknown_drops:
        available = ", ".join(sorted(external_names))
        raise ValueError(
            f"Dataset {dataset_path}: --explicit-drop references unknown class(es) "
            f"{unknown_drops}. Available classes: {available}"
        )


def _remap_external_labels(
    label_path: Path,
    external_id_to_name: Mapping[int, str],
    class_map: Mapping[str, str],
    explicit_drops: Optional[set[str]] = None,
) -> Tuple[List[YoloLabel], Counter[str]]:
    remapped: List[YoloLabel] = []
    dropped_explicit: Counter[str] = Counter()
    drops = explicit_drops or set()
    for class_id, xc, yc, bw, bh in _read_yolo_label(label_path):
        external_name = external_id_to_name.get(class_id)
        if external_name is None:
            continue
        target_name = class_map.get(external_name)
        if target_name is None:
            if external_name in drops:
                dropped_explicit[external_name] += 1
            continue
        remapped.append((CLASS_TO_ID[target_name], xc, yc, bw, bh))
    return remapped, dropped_explicit


def merge_external_dataset(
    dataset_path: Path,
    class_map: Mapping[str, str],
    output_dir: Path,
    split_ratios: Tuple[float, float, float],
    seed: int = DEFAULT_SEED,
    stem_meta: Optional[StemMeta] = None,
    balance_strategy: str = "none",
    balance_sources: Optional[Sequence[str]] = None,
    balance_target: Optional[int] = None,
    explicit_drops: Optional[set[str]] = None,
) -> ExternalMergeSummary:
    """
    Merge a Roboflow / external YOLO dataset into the unified Talap output.

    Example CLI:
        --extra-dataset /data/roboflow_potholes:manhole=sunken_manhole,pothole=pothole
    """
    yaml_path = dataset_path / "data.yaml"
    external_id_to_name = parse_external_data_yaml(yaml_path)
    drops = explicit_drops or set()
    _validate_class_map_against_dataset(dataset_path, class_map, external_id_to_name, drops)
    warn_unmapped_classes(dataset_path, class_map, external_id_to_name, drops)

    pairs = _discover_external_image_label_pairs(dataset_path)
    if not pairs:
        raise FileNotFoundError(
            f"No image/label pairs found under {dataset_path}. "
            "Expected images/ + labels/ (or train/valid subfolders)."
        )

    valid_items: List[Tuple[Path, List[YoloLabel], str]] = []
    skipped_empty = 0
    class_distribution: Counter[str] = Counter()
    explicit_drop_totals: Counter[str] = Counter()
    dataset_slug = re.sub(r"[^\w\-]+", "_", dataset_path.name).strip("_") or "external"

    for image, label_path in pairs:
        remapped, dropped = _remap_external_labels(
            label_path, external_id_to_name, class_map, drops
        )
        explicit_drop_totals.update(dropped)
        if not remapped:
            skipped_empty += 1
            continue
        stem = f"ext_{dataset_slug}_{image.stem}"
        valid_items.append((image, remapped, stem))
        if stem_meta is not None:
            subgroup = infer_subgroup_from_image_stem(image.stem)
            stem_meta[stem] = (dataset_path.name, subgroup)
        for class_id, *_ in remapped:
            class_distribution[CLASS_NAMES[class_id]] += 1

    if explicit_drop_totals:
        dropped_summary = ", ".join(
            f"{name}={count}" for name, count in sorted(explicit_drop_totals.items())
        )
        print(
            f"INFO: Dataset {dataset_path.name}: explicitly dropped boxes via "
            f"--explicit-drop: {dropped_summary}"
        )

    subgroup_stats = (
        build_subgroup_stats(valid_items, stem_meta) if stem_meta is not None else []
    )

    train, val, test = stratified_three_way_split(
        valid_items,
        stratify_key=lambda item: _primary_class_id(item[1]),
        ratios=split_ratios,
        seed=seed,
    )
    balance_sources_set = set(balance_sources or [])
    if balance_strategy != "none" and dataset_path.name in balance_sources_set and stem_meta is not None:
        train_stats = build_subgroup_stats(train, stem_meta)
        default_target = max((s.images for s in train_stats), default=0)
        target = balance_target or default_target
        train, balance_logs = apply_subgroup_balance(
            train, stem_meta, dataset_path.name, balance_strategy, target, seed=seed + 100
        )
        for line in balance_logs:
            print(line)

    counts = _write_split_items(output_dir, {"train": train, "val": val, "test": test})

    return ExternalMergeSummary(
        dataset_name=dataset_path.name,
        total_images=len(pairs),
        kept_images=len(valid_items),
        skipped_empty=skipped_empty,
        train_count=counts["train"],
        val_count=counts["val"],
        test_count=counts["test"],
        class_distribution=dict(class_distribution),
        subgroup_stats=subgroup_stats,
    )


def write_data_yaml(dataset_root: Path, yaml_name: str = "data.yaml", include_test: bool = True) -> Path:
    yaml_path = dataset_root / yaml_name
    lines = [
        f"path: {dataset_root.resolve()}",
        "train: images/train",
        "val: images/val",
    ]
    if include_test:
        lines.append("test: images/test")
    lines.extend([f"nc: {len(CLASS_NAMES)}", f"names: {CLASS_NAMES}"])
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yaml_path


def count_split_images(output_dir: Path) -> SplitCounts:
    counts = {"train": 0, "val": 0, "test": 0}
    for split in SPLIT_NAMES:
        images_dir = output_dir / "images" / split
        if images_dir.is_dir():
            counts[split] = len(list(images_dir.glob("*")))
    return counts


def build_kz_only_subset(output_dir: Path, prefix: str = "kz_") -> Path | None:
    """
    Symlink KZ train+val images into kz_only/ for stage-1 fine-tuning.
    Never includes the held-out test split.
    """
    kz_root = output_dir / "kz_only"
    found = 0
    for split in ("train", "val"):
        src_images = output_dir / "images" / split
        src_labels = output_dir / "labels" / split
        if not src_images.is_dir():
            continue
        dst_images = kz_root / "images" / split
        dst_labels = kz_root / "labels" / split
        dst_images.mkdir(parents=True, exist_ok=True)
        dst_labels.mkdir(parents=True, exist_ok=True)
        for img in sorted(src_images.glob(f"{prefix}*")):
            label = src_labels / f"{img.stem}.txt"
            if not label.is_file():
                continue
            dst_img = dst_images / img.name
            dst_lab = dst_labels / label.name
            if not dst_img.exists():
                dst_img.symlink_to(img.resolve())
            if not dst_lab.exists():
                dst_lab.symlink_to(label.resolve())
            found += 1
    if found == 0:
        return None
    return write_data_yaml(kz_root, yaml_name="data.yaml", include_test=False)


def print_split_audit_table(sources: Sequence[SourceSplitCounts | ExternalMergeSummary]) -> None:
    rows: List[Tuple[str, int, int, int]] = []
    totals = {"train": 0, "val": 0, "test": 0}
    for src in sources:
        if isinstance(src, ExternalMergeSummary):
            name = src.dataset_name
            train, val, test = src.train_count, src.val_count, src.test_count
        else:
            name = src.source
            train, val, test = src.train, src.val, src.test
        rows.append((name, train, val, test))
        totals["train"] += train
        totals["val"] += val
        totals["test"] += test

    col_w = max(len(r[0]) for r in rows + [("TOTAL", 0, 0, 0)])
    header = f"{'source'.ljust(col_w)}  {'train':>6}  {'val':>6}  {'test':>6}"
    print(header)
    print("-" * len(header))
    for name, train, val, test in rows:
        print(f"{name.ljust(col_w)}  {train:6d}  {val:6d}  {test:6d}")
    print("-" * len(header))
    print(f"{'TOTAL'.ljust(col_w)}  {totals['train']:6d}  {totals['val']:6d}  {totals['test']:6d}")


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Prepare RDD2022, KZ photos, and external YOLO datasets for Talap training",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python training/prepare_dataset.py --rdd-root /data/RDD2022\n"
            "  python training/prepare_dataset.py --split-ratios 0.70,0.15,0.15 \\\n"
            "    --extra-dataset /data/roboflow_potholes:manhole=sunken_manhole,pothole=pothole\n"
            "  python training/prepare_dataset.py \\\n"
            "    --extra-dataset /data/hf_rdd:longitudinal_crack=crack_longitudinal,"
            "transverse_crack=crack_longitudinal,pothole=pothole \\\n"
            "    --explicit-drop /data/hf_rdd:alligator_crack\n"
        ),
    )
    parser.add_argument("--rdd-root", type=Path, help="RDD2022 root directory")
    parser.add_argument(
        "--rdd-countries",
        type=str,
        default="",
        help="Comma-separated RDD2022 country folders to include (e.g. Japan,India)",
    )
    parser.add_argument("--kz-dir", type=Path, help="Custom KZ photos in YOLO format")
    parser.add_argument(
        "--extra-dataset",
        action="append",
        default=[],
        metavar="PATH:CLASS_MAP",
        help="External YOLO dataset with class remap (repeatable)",
    )
    parser.add_argument(
        "--explicit-drop",
        action="append",
        default=[],
        metavar="PATH:CLASS1,CLASS2",
        help=(
            "Deliberately exclude external class names for a dataset (repeatable). "
            "Unmapped classes not listed here trigger a WARNING at prepare-time."
        ),
    )
    parser.add_argument("--output", type=Path, default=Path("training/dataset"))
    parser.add_argument(
        "--split-ratios",
        type=str,
        default=DEFAULT_SPLIT_RATIOS_STR,
        help="Train,val,test fractions (default 0.70,0.15,0.15)",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=None,
        help="[legacy] Val fraction; with --split-ratio disables test split",
    )
    parser.add_argument(
        "--split-ratio",
        type=float,
        default=None,
        help="[legacy] Train fraction for external datasets",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--report-balance",
        action="store_true",
        help="Print per-source/country image and class-instance balance table after merge",
    )
    parser.add_argument(
        "--balance-strategy",
        choices=("none", "oversample", "cap"),
        default="none",
        help="Optional train-split rebalancing for opted-in sources (default: none)",
    )
    parser.add_argument(
        "--balance-target",
        type=int,
        default=None,
        help="Target image count per subgroup when balancing (default: largest subgroup in source)",
    )
    parser.add_argument(
        "--balance-source",
        action="append",
        default=[],
        metavar="NAME",
        help="Source/dataset name to balance (repeatable; required for --balance-strategy to take effect)",
    )
    args = parser.parse_args(argv)

    if not args.rdd_root and not args.kz_dir and not args.extra_dataset:
        parser.error("Provide at least one of --rdd-root, --kz-dir, or --extra-dataset")

    split_ratios = resolve_split_ratios(args.split_ratios, args.val_ratio, args.split_ratio)
    output_dir = args.output
    audit_sources: List[SourceSplitCounts | ExternalMergeSummary] = []
    stem_meta: StemMeta = {}
    explicit_drops_by_path: Dict[Path, set[str]] = {}
    for entry in args.explicit_drop:
        drop_path, drop_names = parse_explicit_drop_arg(entry)
        explicit_drops_by_path[drop_path.resolve()] = drop_names
    balance_sources = [s.strip() for s in args.balance_source if s.strip()]
    if args.balance_strategy != "none" and not balance_sources:
        print(
            "NOTE: --balance-strategy is set but no --balance-source was given; "
            "skipping rebalancing (KZ / manhole / rutting are never auto-balanced)."
        )

    rdd_countries = [c.strip() for c in args.rdd_countries.split(",") if c.strip()] or None

    if args.rdd_root:
        rdd_counts = prepare_rdd2022(
            args.rdd_root,
            output_dir,
            split_ratios=split_ratios,
            seed=args.seed,
            countries=rdd_countries,
            stem_meta=stem_meta,
            balance_strategy=args.balance_strategy,
            balance_sources=balance_sources,
            balance_target=args.balance_target,
        )
        audit_sources.append(rdd_counts)

    if args.kz_dir:
        kz_counts = merge_kz_photos(args.kz_dir, output_dir, split_ratios=split_ratios, seed=args.seed)
        audit_sources.append(kz_counts)
        kz_yaml = build_kz_only_subset(output_dir)
        if kz_yaml:
            print(f"KZ-only stage-1 config (train+val only, no test): {kz_yaml}")

    for entry in args.extra_dataset:
        dataset_path, class_map = parse_extra_dataset_arg(entry)
        summary = merge_external_dataset(
            dataset_path,
            class_map,
            output_dir,
            split_ratios=split_ratios,
            seed=hash((args.seed, dataset_path.name)) % (2**31),
            stem_meta=stem_meta,
            balance_strategy=args.balance_strategy,
            balance_sources=balance_sources,
            balance_target=args.balance_target,
            explicit_drops=resolve_explicit_drops_for_dataset(
                dataset_path, explicit_drops_by_path
            ),
        )
        audit_sources.append(summary)
        if summary.class_distribution:
            dist = ", ".join(
                f"{name}={count}" for name, count in sorted(summary.class_distribution.items())
            )
            print(f"  [{summary.dataset_name}] class distribution after remap: {dist}")

    if audit_sources:
        print("\nPer-source split audit (stratified per source, seed=%d):" % args.seed)
        print_split_audit_table(audit_sources)

    if args.report_balance:
        all_subgroup_stats = []
        for src in audit_sources:
            if isinstance(src, ExternalMergeSummary) and src.subgroup_stats:
                all_subgroup_stats.extend(src.subgroup_stats)
            elif isinstance(src, SourceSplitCounts) and src.subgroup_stats:
                all_subgroup_stats.extend(src.subgroup_stats)
        if all_subgroup_stats:
            print_balance_report(all_subgroup_stats)
        elif stem_meta:
            # Reconstruct from stem_meta if only RDD path was used
            all_items = []
            for split in SPLIT_NAMES:
                images_dir = output_dir / "images" / split
                labels_dir = output_dir / "labels" / split
                if not images_dir.is_dir():
                    continue
                for image in images_dir.iterdir():
                    label_path = labels_dir / f"{image.stem}.txt"
                    if label_path.is_file():
                        all_items.append((image, _read_yolo_label(label_path), image.stem))
            print_balance_report(build_subgroup_stats(all_items, stem_meta))
        else:
            print("\nBalance report: no subgroup metadata available for merged sources.")

    has_test = split_ratios[2] > 0
    yaml_path = write_data_yaml(output_dir, include_test=has_test)
    combined = count_split_images(output_dir)
    print(
        f"\nWrote {yaml_path} "
        f"(combined: {combined['train']} train, {combined['val']} val, {combined['test']} test images)"
    )
    if has_test:
        print("NOTE: test split is held out — use only via training/eval.py --split test")


if __name__ == "__main__":
    main()
