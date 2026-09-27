"""Subgroup balance reporting and optional train-split rebalancing."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

PreparedItem = Tuple[Path, "List[YoloLabel]", str]
StemMeta = Dict[str, Tuple[str, Optional[str]]]  # stem -> (source, subgroup)


@dataclass
class SubgroupStats:
    source: str
    subgroup: str
    images: int = 0
    instances: Dict[str, int] = field(default_factory=dict)


def infer_subgroup_from_image_stem(stem: str) -> Optional[str]:
    """Infer country/subgroup from HF-style or RDD-style image stems."""
    prefixes = (
        "United_States",
        "China_MotorBike",
        "China_Drone",
        "Japan",
        "India",
        "Czech",
        "Norway",
    )
    for prefix in prefixes:
        if stem.startswith(f"{prefix}_"):
            return prefix
    return None


def build_subgroup_stats(
    items: Sequence[PreparedItem],
    stem_meta: StemMeta,
) -> List[SubgroupStats]:
    from training.prepare_dataset import CLASS_NAMES

    grouped: Dict[Tuple[str, str], SubgroupStats] = {}
    for _image, labels, stem in items:
        source, subgroup = stem_meta.get(stem, ("unknown", None))
        subgroup = subgroup or "unknown"
        key = (source, subgroup)
        if key not in grouped:
            grouped[key] = SubgroupStats(source=source, subgroup=subgroup)
        stats = grouped[key]
        stats.images += 1
        for class_id, *_ in labels:
            class_name = CLASS_NAMES[class_id]
            stats.instances[class_name] = stats.instances.get(class_name, 0) + 1
    return sorted(grouped.values(), key=lambda s: (s.source, s.subgroup))


def print_balance_report(stats: Sequence[SubgroupStats], title: str = "Balance report") -> None:
    if not stats:
        print(f"\n{title}: no subgroup metadata available.")
        return

    print(f"\n{title} (by source / subgroup):")
    col_source = max(len(s.source) for s in stats)
    col_subgroup = max(len(s.subgroup) for s in stats)
    header = (
        f"{'source'.ljust(col_source)}  "
        f"{'subgroup'.ljust(col_subgroup)}  "
        f"{'images':>7}  instances"
    )
    print(header)
    print("-" * len(header))
    for row in stats:
        inst = ", ".join(f"{k}={v}" for k, v in sorted(row.instances.items()))
        print(
            f"{row.source.ljust(col_source)}  "
            f"{row.subgroup.ljust(col_subgroup)}  "
            f"{row.images:7d}  {inst or '-'}"
        )


def _subgroup_of(stem: str, stem_meta: StemMeta) -> str:
    _, subgroup = stem_meta.get(stem, ("unknown", None))
    return subgroup or "unknown"


def apply_subgroup_balance(
    train_items: List[PreparedItem],
    stem_meta: StemMeta,
    source_name: str,
    strategy: str,
    target: int,
    seed: int,
) -> Tuple[List[PreparedItem], List[str]]:
    """Rebalance train items for one source across its subgroups."""
    if strategy == "none":
        return train_items, []

    rng = random.Random(seed)
    logs: List[str] = []
    by_subgroup: Dict[str, List[PreparedItem]] = defaultdict(list)
    for item in train_items:
        by_subgroup[_subgroup_of(item[2], stem_meta)].append(item)

    if not by_subgroup:
        return train_items, logs

    effective_target = target or max(len(items) for items in by_subgroup.values())
    balanced: List[PreparedItem] = []

    for subgroup, items in sorted(by_subgroup.items()):
        count = len(items)
        if strategy == "cap" and count > effective_target:
            chosen = rng.sample(items, effective_target)
            dropped = count - effective_target
            balanced.extend(chosen)
            logs.append(
                f"[balance cap] {source_name}/{subgroup}: "
                f"subsampled {count} -> {effective_target} (dropped {dropped})"
            )
        elif strategy == "oversample" and count < effective_target:
            balanced.extend(items)
            dup_round = 0
            while len([i for i in balanced if _subgroup_of(i[2], stem_meta) == subgroup]) < effective_target:
                orig = items[dup_round % len(items)]
                dup_stem = f"{orig[2]}_bal{dup_round}"
                balanced.append((orig[0], orig[1], dup_stem))
                stem_meta[dup_stem] = stem_meta[orig[2]]
                logs.append(
                    f"[balance oversample] {source_name}/{subgroup}: "
                    f"duplicated {orig[2]} -> {dup_stem} (factor ~{effective_target / count:.2f}x)"
                )
                dup_round += 1
        else:
            balanced.extend(items)
            if strategy == "oversample" and count == effective_target:
                logs.append(f"[balance oversample] {source_name}/{subgroup}: already at target ({count})")

    return balanced, logs
