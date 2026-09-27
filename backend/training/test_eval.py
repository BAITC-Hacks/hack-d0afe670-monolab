"""Tests for eval.py comparison and guardrails."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from training.eval import _f1, print_compare_delta


def test_f1() -> None:
    assert _f1(0.8, 0.6) == pytest.approx(0.6857, rel=1e-3)
    assert _f1(0.0, 0.0) == 0.0


def test_print_compare_delta(capsys) -> None:
    current = {
        "weights": "best.pt",
        "run_tag": "eval",
        "overall": {"map50": 0.5, "map50_95": 0.3, "precision": 0.6, "recall": 0.4},
        "per_class": [{"class": "pothole", "ap50": 0.55}],
    }
    baseline = {
        "weights": "yolo26s.pt",
        "run_tag": "baseline_pretrained",
        "overall": {"map50": 0.2, "map50_95": 0.1, "precision": 0.3, "recall": 0.2},
        "per_class": [{"class": "pothole", "ap50": 0.02}],
    }
    print_compare_delta(current, baseline)
    out = capsys.readouterr().out
    assert "Comparison" in out
    assert "map50" in out
    assert "pothole" in out
