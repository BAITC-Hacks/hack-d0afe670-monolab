#!/usr/bin/env python3
"""Count raw RDD2022 damage codes in XML annotations (before Talap mapping)."""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

RDD_ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "/Users/darkhan/data/RDD2022/RDD2022")


def main() -> None:
    if not RDD_ROOT.is_dir():
        print(f"RDD root not found: {RDD_ROOT}")
        sys.exit(1)

    code_counts: Counter[str] = Counter()
    xml_per_country: Counter[str] = Counter()
    img_per_country: Counter[str] = Counter()
    total_xml = 0
    total_train_img = 0

    for country_dir in sorted(RDD_ROOT.iterdir()):
        if not country_dir.is_dir():
            continue
        country = country_dir.name
        train_img = country_dir / "train" / "images"
        train_xml = country_dir / "train" / "annotations" / "xmls"
        if train_img.is_dir():
            n_img = len(list(train_img.glob("*.jpg")))
            img_per_country[country] = n_img
            total_train_img += n_img
        if not train_xml.is_dir():
            print(f"  {country}: NO train/annotations/xmls")
            continue
        for xml_path in train_xml.glob("*.xml"):
            xml_per_country[country] += 1
            total_xml += 1
            try:
                root = ET.parse(xml_path).getroot()
            except ET.ParseError:
                continue
            for obj in root.findall("object"):
                code = (obj.findtext("name") or "").strip()
                if code:
                    code_counts[code] += 1

    print("=== Per-country train images ===")
    for c, n in sorted(img_per_country.items()):
        print(f"  {c}: {n} images")
    print(f"  TOTAL: {total_train_img} images")

    print("\n=== Per-country train XML files ===")
    for c, n in sorted(xml_per_country.items()):
        print(f"  {c}: {n} xml")
    print(f"  TOTAL: {total_xml} xml")

    print("\n=== Raw damage code counts (all <object><name>) ===")
    for code, n in sorted(code_counts.items()):
        print(f"  {code}: {n}")
    print(f"  TOTAL objects: {sum(code_counts.values())}")

    print("\n=== Talap mapping preview (no code changes) ===")
    mapping = {"D00": "crack_longitudinal", "D10": "crack_longitudinal", "D20": "crack_alligator", "D40": "pothole"}
    kept = sum(code_counts.get(k, 0) for k in mapping)
    dropped = sum(code_counts.values()) - kept
    unknown = {k: v for k, v in code_counts.items() if k not in mapping}
    print(f"  Mapped to Talap taxonomy: {kept}")
    print(f"  D10 (transverse) → crack_longitudinal: {code_counts.get('D10', 0)}")
    print(f"  Unmapped/dropped codes: {unknown}")


if __name__ == "__main__":
    main()
