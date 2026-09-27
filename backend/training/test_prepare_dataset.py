"""Tests for external YOLO dataset merge in prepare_dataset.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from training.prepare_dataset import (
    CLASS_TO_ID,
    _discover_rdd_pairs,
    merge_external_dataset,
    parse_class_map,
    parse_extra_dataset_arg,
    prepare_rdd2022,
    warn_unmapped_classes,
    warn_unmapped_transverse_classes,
)
from training.balance_utils import StemMeta
from training.split_utils import parse_split_ratios, stratified_three_way_split


def _write_external_dataset(root: Path) -> None:
    (root / "images").mkdir(parents=True)
    (root / "labels").mkdir(parents=True)
    (root / "data.yaml").write_text(
        "path: .\n"
        "train: images\n"
        "val: images\n"
        "nc: 3\n"
        "names: ['pothole', 'manhole', 'car']\n",
        encoding="utf-8",
    )

    (root / "images" / "img0.jpg").write_bytes(b"img0")
    (root / "labels" / "img0.txt").write_text(
        f"{0} 0.5 0.5 0.2 0.2\n{2} 0.1 0.1 0.1 0.1\n",
        encoding="utf-8",
    )

    (root / "images" / "img1.jpg").write_bytes(b"img1")
    (root / "labels" / "img1.txt").write_text("1 0.4 0.4 0.15 0.15\n", encoding="utf-8")

    (root / "images" / "img2.jpg").write_bytes(b"img2")
    (root / "labels" / "img2.txt").write_text("2 0.3 0.3 0.1 0.1\n", encoding="utf-8")

    (root / "images" / "img3.jpg").write_bytes(b"img3")
    (root / "labels" / "img3.txt").write_text("0 0.6 0.6 0.2 0.2\n", encoding="utf-8")


def test_parse_class_map_and_extra_dataset_arg(tmp_path: Path) -> None:
    dataset = tmp_path / "roboflow_export"
    dataset.mkdir()
    class_map = parse_class_map("manhole=sunken_manhole,pothole=pothole")
    assert class_map == {"manhole": "sunken_manhole", "pothole": "pothole"}

    path, parsed_map = parse_extra_dataset_arg(f"{dataset}:manhole=sunken_manhole")
    assert path == dataset
    assert parsed_map["manhole"] == "sunken_manhole"


def test_parse_split_ratios() -> None:
    assert parse_split_ratios("0.70,0.15,0.15") == (0.70, 0.15, 0.15)
    with pytest.raises(ValueError, match="sum to 1.0"):
        parse_split_ratios("0.5,0.5,0.5")


def test_stratified_three_way_split_is_reproducible() -> None:
    items = [(i, [i % 3]) for i in range(30)]
    a_train, a_val, a_test = stratified_three_way_split(
        items, stratify_key=lambda x: x[1][0], ratios=(0.7, 0.15, 0.15), seed=42
    )
    b_train, b_val, b_test = stratified_three_way_split(
        items, stratify_key=lambda x: x[1][0], ratios=(0.7, 0.15, 0.15), seed=42
    )
    assert [x[0] for x in a_train] == [x[0] for x in b_train]
    assert len(a_train) + len(a_val) + len(a_test) == 30


def test_merge_external_dataset_remaps_and_filters(tmp_path: Path) -> None:
    external = tmp_path / "external_ds"
    output = tmp_path / "dataset"
    _write_external_dataset(external)

    class_map = {"pothole": "pothole", "manhole": "sunken_manhole"}
    summary = merge_external_dataset(
        external,
        class_map,
        output,
        split_ratios=(0.70, 0.15, 0.15),
        seed=42,
    )

    assert summary.total_images == 4
    assert summary.kept_images == 3
    assert summary.skipped_empty == 1
    assert summary.class_distribution["pothole"] == 2
    assert summary.class_distribution["sunken_manhole"] == 1
    assert summary.train_count + summary.val_count + summary.test_count == 3

    all_labels = list((output / "labels" / "train").glob("*.txt"))
    all_labels += list((output / "labels" / "val").glob("*.txt"))
    all_labels += list((output / "labels" / "test").glob("*.txt"))
    assert len(all_labels) == 3

    all_class_ids = set()
    for label_path in all_labels:
        for line in label_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                all_class_ids.add(int(line.split()[0]))
    assert all_class_ids == {CLASS_TO_ID["pothole"], CLASS_TO_ID["sunken_manhole"]}

    assert not any("img2" in p.name for p in (output / "images" / "train").glob("*"))
    assert not any("img2" in p.name for p in (output / "images" / "val").glob("*"))
    assert not any("img2" in p.name for p in (output / "images" / "test").glob("*"))


def test_merge_external_dataset_raises_on_unknown_class_map_entry(tmp_path: Path) -> None:
    external = tmp_path / "external_ds"
    output = tmp_path / "dataset"
    _write_external_dataset(external)

    with pytest.raises(ValueError, match="unknown external class 'missing_class'"):
        merge_external_dataset(
            external,
            {"missing_class": "pothole"},
            output,
            split_ratios=(0.7, 0.15, 0.15),
        )


def _write_rdd_country(root: Path, country: str) -> None:
    images_dir = root / country / "train" / "images"
    xml_dir = root / country / "train" / "annotations" / "xmls"
    images_dir.mkdir(parents=True)
    xml_dir.mkdir(parents=True)
    (images_dir / f"{country}_001.jpg").write_bytes(b"img")
    (xml_dir / f"{country}_001.xml").write_text(
        (
            "<annotation><size><width>100</width><height>100</height></size>"
            "<object><name>D40</name><bndbox><xmin>10</xmin><ymin>10</ymin>"
            "<xmax>30</xmax><ymax>30</ymax></bndbox></object></annotation>"
        ),
        encoding="utf-8",
    )


def test_discover_rdd_pairs_filters_countries(tmp_path: Path) -> None:
    rdd_root = tmp_path / "RDD2022"
    _write_rdd_country(rdd_root, "Japan")
    _write_rdd_country(rdd_root, "India")
    _write_rdd_country(rdd_root, "Czech")

    all_pairs = _discover_rdd_pairs(rdd_root)
    filtered_pairs = _discover_rdd_pairs(rdd_root, countries=["Japan", "India"])

    assert len(all_pairs) == 3
    assert len(filtered_pairs) == 2
    assert all("Japan" in str(image) or "India" in str(image) for image, _ in filtered_pairs)


def _write_two_subgroup_dataset(root: Path, name: str, subgroup: str, count: int) -> None:
    (root / "images").mkdir(parents=True, exist_ok=True)
    (root / "labels").mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text(
        "names: ['pothole']\n",
        encoding="utf-8",
    )
    for i in range(count):
        stem = f"{subgroup}_{i:03d}"
        (root / "images" / f"{stem}.jpg").write_bytes(b"img")
        (root / "labels" / f"{stem}.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")


def test_balance_oversample_only_opted_in_source(tmp_path: Path) -> None:
    source_a = tmp_path / "source_a"
    source_b = tmp_path / "source_b"
    output = tmp_path / "dataset"
    _write_two_subgroup_dataset(source_a, "source_a", "Japan", 2)
    _write_two_subgroup_dataset(source_a, "source_a", "India", 6)
    _write_two_subgroup_dataset(source_b, "source_b", "Japan", 10)

    stem_meta: StemMeta = {}
    merge_external_dataset(
        source_a,
        {"pothole": "pothole"},
        output,
        split_ratios=(1.0, 0.0, 0.0),
        seed=42,
        stem_meta=stem_meta,
        balance_strategy="oversample",
        balance_sources=["source_a"],
        balance_target=6,
    )
    merge_external_dataset(
        source_b,
        {"pothole": "pothole"},
        output,
        split_ratios=(1.0, 0.0, 0.0),
        seed=43,
        stem_meta=stem_meta,
        balance_strategy="oversample",
        balance_sources=["source_a"],
        balance_target=6,
    )
    train_images = list((output / "images" / "train").glob("*"))
    source_a_train = [p for p in train_images if "source_a" in p.name]
    source_b_train = [p for p in train_images if "source_b" in p.name]

    # Japan(2) oversampled to 6 + India(6) unchanged = 12; source_b not opted in -> 10
    assert len(source_a_train) == 12
    assert len(source_b_train) == 10


def test_explicit_drop_mapped_survives_dropped_silent_unmapped_warns(
    tmp_path: Path, capsys
) -> None:
    external = tmp_path / "multi_class_ds"
    output = tmp_path / "dataset"
    (external / "images").mkdir(parents=True)
    (external / "labels").mkdir(parents=True)
    (external / "data.yaml").write_text(
        "names: ['pothole', 'manhole', 'car']\n",
        encoding="utf-8",
    )
    (external / "images" / "img0.jpg").write_bytes(b"img0")
    (external / "labels" / "img0.txt").write_text(
        "0 0.5 0.5 0.2 0.2\n1 0.4 0.4 0.15 0.15\n2 0.3 0.3 0.1 0.1\n",
        encoding="utf-8",
    )

    summary = merge_external_dataset(
        external,
        {"pothole": "pothole"},
        output,
        split_ratios=(1.0, 0.0, 0.0),
        explicit_drops={"manhole"},
    )
    captured = capsys.readouterr().out

    assert summary.kept_images == 1
    assert summary.class_distribution == {"pothole": 1}
    assert "INFO:" in captured
    assert "manhole=1" in captured
    assert "WARNING" in captured
    assert "car" in captured

    label_text = (output / "labels" / "train" / "ext_multi_class_ds_img0.txt").read_text()
    assert label_text.strip() == f"{CLASS_TO_ID['pothole']} 0.500000 0.500000 0.200000 0.200000"


def test_transverse_warning_when_unmapped(capsys) -> None:
    external_names = {0: "longitudinal_crack", 1: "transverse_crack", 2: "pothole"}
    class_map = {"longitudinal_crack": "crack_longitudinal", "pothole": "pothole"}
    warn_unmapped_transverse_classes(Path("/data/hf_rdd"), class_map, external_names)
    captured = capsys.readouterr().out
    assert "WARNING" in captured
    assert "transverse_crack" in captured


def test_transverse_warning_silent_when_mapped(capsys) -> None:
    external_names = {0: "longitudinal_crack", 1: "transverse_crack", 2: "pothole"}
    class_map = {
        "longitudinal_crack": "crack_longitudinal",
        "transverse_crack": "crack_longitudinal",
        "pothole": "pothole",
    }
    warn_unmapped_classes(Path("/data/hf_rdd"), class_map, external_names)
    captured = capsys.readouterr().out
    assert "WARNING" not in captured


def test_transverse_warning_silent_when_explicitly_dropped(capsys) -> None:
    external_names = {0: "longitudinal_crack", 1: "transverse_crack", 2: "pothole"}
    class_map = {"longitudinal_crack": "crack_longitudinal", "pothole": "pothole"}
    warn_unmapped_classes(
        Path("/data/hf_rdd"),
        class_map,
        external_names,
        explicit_drops={"transverse_crack"},
    )
    captured = capsys.readouterr().out
    assert "WARNING" not in captured


def test_merge_external_dataset_raises_on_missing_data_yaml(tmp_path: Path) -> None:
    external = tmp_path / "broken_ds"
    external.mkdir()
    (external / "images").mkdir()
    (external / "labels").mkdir()

    with pytest.raises(FileNotFoundError, match="data.yaml not found"):
        merge_external_dataset(
            external,
            {"pothole": "pothole"},
            tmp_path / "out",
            split_ratios=(0.7, 0.15, 0.15),
        )
