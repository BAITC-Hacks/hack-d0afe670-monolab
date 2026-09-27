"""Reproducible stratified train/val/test splitting for YOLO datasets."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Callable, Dict, List, Sequence, Tuple, TypeVar

T = TypeVar("T")

SPLIT_NAMES = ("train", "val", "test")


def parse_split_ratios(ratios_str: str) -> Tuple[float, float, float]:
    parts = [p.strip() for p in ratios_str.split(",")]
    if len(parts) != 3:
        raise ValueError("--split-ratios must be 'train,val,test' (three comma-separated floats)")
    ratios = tuple(float(p) for p in parts)
    total = sum(ratios)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"--split-ratios must sum to 1.0, got {total:.6f}")
    if any(r < 0 for r in ratios):
        raise ValueError("--split-ratios values must be non-negative")
    return ratios


def resolve_split_ratios(
    split_ratios_str: str,
    val_ratio: float | None,
    split_ratio: float | None,
) -> Tuple[float, float, float]:
    """New default is 70/15/15. Legacy --val-ratio/--split-ratio yields no test split."""
    if val_ratio is not None or split_ratio is not None:
        train = split_ratio if split_ratio is not None else 1.0 - (val_ratio or 0.15)
        val = val_ratio if val_ratio is not None else 1.0 - train
        if train + val > 1.0 + 1e-6:
            raise ValueError("Legacy --split-ratio + --val-ratio exceed 1.0")
        return (train, val, max(0.0, 1.0 - train - val))
    return parse_split_ratios(split_ratios_str)


def _allocate_counts(n: int, ratios: Tuple[float, float, float]) -> Tuple[int, int, int]:
    if n == 0:
        return 0, 0, 0
    raw = [n * ratios[0], n * ratios[1], n * ratios[2]]
    counts = [int(x) for x in raw]
    remainder = n - sum(counts)
    fractions = [raw[i] - counts[i] for i in range(3)]
    order = sorted(range(3), key=lambda i: fractions[i], reverse=True)
    for i in order:
        if remainder <= 0:
            break
        counts[i] += 1
        remainder -= 1
    # Ensure at least one val item when n>=2 and val ratio > 0
    if n >= 2 and ratios[1] > 0 and counts[1] == 0:
        if counts[0] > 1:
            counts[0] -= 1
            counts[1] += 1
        elif counts[2] > 0:
            counts[2] -= 1
            counts[1] += 1
    if n >= 3 and ratios[2] > 0 and counts[2] == 0:
        donor = 0 if counts[0] > 1 else 1
        if counts[donor] > 0:
            counts[donor] -= 1
            counts[2] += 1
    return counts[0], counts[1], counts[2]


def stratified_three_way_split(
    items: Sequence[T],
    stratify_key: Callable[[T], int],
    ratios: Tuple[float, float, float],
    seed: int,
) -> Tuple[List[T], List[T], List[T]]:
    """
    Stratify items by an integer class key (dominant label), then split each
    stratum independently into train/val/test using fixed ratios + seed.
    """
    if not items:
        return [], [], []

    rng = random.Random(seed)
    buckets: Dict[int, List[T]] = defaultdict(list)
    for item in items:
        buckets[stratify_key(item)].append(item)

    train: List[T] = []
    val: List[T] = []
    test: List[T] = []

    for bucket_key in sorted(buckets.keys()):
        bucket = list(buckets[bucket_key])
        rng.shuffle(bucket)
        n_train, n_val, n_test = _allocate_counts(len(bucket), ratios)
        train.extend(bucket[:n_train])
        val.extend(bucket[n_train : n_train + n_val])
        test.extend(bucket[n_train + n_val : n_train + n_val + n_test])

    rng.shuffle(train)
    rng.shuffle(val)
    rng.shuffle(test)
    return train, val, test
