#!/usr/bin/env python3
"""
Download a country subset of RDD2022 from the Hugging Face YOLO export.

Official per-country S3 zips currently return 403. This script pulls only the
requested countries (~0.9 GB for Japan + India) instead of the full 12 GB Figshare
archive.

Usage:
    python training/download_rdd2022_subset.py --countries Japan,India \\
        --output /Users/darkhan/data/RDD2022_japan_india
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Sequence, Tuple

HF_REPO = "dronefreak/RDD2022"
HF_API = f"https://huggingface.co/api/datasets/{HF_REPO}/tree/main"
HF_RESOLVE = f"https://huggingface.co/datasets/{HF_REPO}/resolve/main"
SPLITS = ("train", "valid", "test")
DATA_YAML = """path: .
train: images
val: images
test: images
nc: 4
names: ['longitudinal_crack', 'transverse_crack', 'alligator_crack', 'pothole']
"""


def _list_shard_files(split: str, shard: int) -> List[dict]:
    url = f"{HF_API}/data/images/{split}/shard_{shard:03d}?recursive=true"
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def _country_prefixes(countries: Sequence[str]) -> Tuple[str, ...]:
    return tuple(f"{country.strip()}_" for country in countries if country.strip())


def discover_image_paths(countries: Sequence[str]) -> List[str]:
    prefixes = _country_prefixes(countries)
    if not prefixes:
        raise ValueError("Provide at least one country name, e.g. Japan,India")

    matched: List[str] = []
    for split in SPLITS:
        shard = 0
        while True:
            try:
                entries = _list_shard_files(split, shard)
            except urllib.error.HTTPError:
                break
            if not entries:
                break

            for entry in entries:
                if entry.get("type") != "file":
                    continue
                rel_path = entry["path"].removeprefix("data/")
                filename = Path(rel_path).name
                if filename.startswith(prefixes):
                    matched.append(rel_path)
            shard += 1

    return sorted(set(matched))


def _download_hf_file(hf_rel_path: str, dest: Path, retries: int = 5) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    url = f"{HF_RESOLVE}/data/{hf_rel_path}"
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                dest.write_bytes(response.read())
            return dest
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 30))
    raise last_error  # type: ignore[misc]


def download_subset(
    countries: Sequence[str],
    output_dir: Path,
    workers: int = 8,
) -> None:
    image_paths = discover_image_paths(countries)
    if not image_paths:
        raise SystemExit(f"No files found for countries: {', '.join(countries)}")

    images_dir = output_dir / "images"
    labels_dir = output_dir / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    jobs: List[Tuple[str, Path]] = []
    for image_path in image_paths:
        filename = Path(image_path).name
        label_path = image_path.replace("images/", "labels/", 1).rsplit(".", 1)[0] + ".txt"
        jobs.append((image_path, images_dir / filename))
        jobs.append((label_path, labels_dir / Path(filename).with_suffix(".txt")))

    total = len(jobs)
    print(
        f"Downloading {len(image_paths)} image/label pairs ({total} files) "
        f"for {', '.join(countries)}"
    )
    print(f"Output: {output_dir}")

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_download_hf_file, src, dest): src for src, dest in jobs}
        for future in as_completed(futures):
            future.result()
            completed += 1
            if completed % 200 == 0 or completed == total:
                print(f"  {completed}/{total} files")

    (output_dir / "data.yaml").write_text(DATA_YAML, encoding="utf-8")
    print("Done.")
    print(
        "Next:\n"
        f"  python training/prepare_dataset.py \\\n"
        f"    --extra-dataset {output_dir}:"
        "longitudinal_crack=crack_longitudinal,transverse_crack=crack_longitudinal,"
        "alligator_crack=crack_alligator,pothole=pothole \\\n"
        f"    --output training/dataset"
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download RDD2022 country subset from Hugging Face")
    parser.add_argument(
        "--countries",
        default="Japan,India",
        help="Comma-separated country folder names (default: Japan,India)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/Users/darkhan/data/RDD2022_japan_india"),
        help="Output directory for flattened YOLO images/labels",
    )
    parser.add_argument("--workers", type=int, default=8, help="Parallel download workers")
    args = parser.parse_args(argv)

    countries = [part.strip() for part in args.countries.split(",") if part.strip()]
    download_subset(countries, args.output, workers=args.workers)


if __name__ == "__main__":
    main(sys.argv[1:])
