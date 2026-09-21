"""t6/N1 regression tests: manual-L1 normalized-IoU dual track.

- manual-L1 with correct shape but wrong absolute scale (the N1 shape:
  fallback S, IoU_abs < 0.90) must PASS via the normalized gate, with the
  absolute numbers kept as advisories;
- aspect/rotation errors must still FAIL (the gate has teeth);
- the dual track must not leak: manual-anchor spoof on L2 still FAILs,
  dimension-anchor behaviour is unchanged (absolute track, no new keys
  required beyond the additive iou_normalized/gate fields).
"""

import copy

import pytest

from cadcraft import geometry as G
from cadcraft.verifier.verifier import (
    VERDICT_FAIL,
    VERDICT_PASS,
    check_report_conformance,
    verify_plan,
)

from helpers_v02 import OUTER_POINTS, make_gt, make_plan, make_single_rect_plan


def _manual_l1_plan(scale_factor=1.058):
    """Single-outer plan, manual anchor, shape ~= truth, scale off."""
    plan = make_plan(anchor_type="manual", scale_factor=scale_factor)
    plan["loops"] = [plan["loops"][0]]
    plan["ribs"] = []
    return plan


def _l1_gt_with_key():
    return {
        "loops": [{"id": "outer_0", "role": "outer",
                   "points": copy.deepcopy(OUTER_POINTS)}],
        "ribs": [],
        "key_dimensions": [{"id": "k_width", "loop_id": "outer_0",
                            "edge": [0, 1], "length_mm": 120.0}],
    }


def test_manual_l1_correct_shape_wrong_scale_passes_normalized():
    plan = _manual_l1_plan(scale_factor=1.058)  # ~N1: abs IoU < 0.90
    gt = _l1_gt_with_key()
    abs_iou = G.polygon_iou(gt["loops"][0]["points"], plan["loops"][0]["points"])
    assert abs_iou < 0.90  # the old absolute-only gate would FAIL
    report = verify_plan(plan, gt, level="L1")
    assert report["verdict"] == VERDICT_PASS, report["reasons"]
    entry = report["per_loop"][0]
    assert entry["gate"] == "normalized"
    assert entry["iou"] == pytest.approx(abs_iou, abs=1e-3)
    assert entry["iou_normalized"] >= 0.90
    assert entry["matched"]
    # Absolute scale error is recorded honestly, but advisory-only.
    assert (report["scale_error_pct"] or 0) > 2.0
    assert report["hard_fails"] == []
    assert any("manual_l1_normalized_gate" in w for w in report["warnings"])
    ok, problems = check_report_conformance(report)
    assert ok, problems


def test_manual_l1_without_keys_passes_and_warns():
    plan = _manual_l1_plan()
    gt = {"loops": [{"id": "outer_0", "role": "outer",
                     "points": copy.deepcopy(OUTER_POINTS)}], "ribs": []}
    report = verify_plan(plan, gt, level="auto")
    assert report["level"] == "L1"
    assert report["verdict"] == VERDICT_PASS, report["reasons"]
    assert report["per_loop"][0]["gate"] == "normalized"


def test_manual_l1_wrong_aspect_still_fails():
    """Normalized gate is shape-only, not a blanket pass: 100x40 plan vs
    100x50 GT (aspect 2.5 vs 2.0) must FAIL."""
    plan = _manual_l1_plan(scale_factor=1.0)
    plan["loops"][0]["points"] = [[0, 0], [100, 0], [100, 50], [0, 50]]
    plan["loops"][0]["area_mm2"] = 5000.0
    gt = {"loops": [{"id": "outer_0", "role": "outer",
                     "points": [[0, 0], [100, 0], [100, 40], [0, 40]]}],
          "ribs": []}
    report = verify_plan(plan, gt, level="L1")
    assert report["verdict"] == VERDICT_FAIL
    entry = report["per_loop"][0]
    assert entry["gate"] == "normalized"
    assert not entry["matched"]
    assert entry["iou_normalized"] < 0.90


def test_manual_anchor_spoof_on_l2_still_fails():
    """The dual track must not leak into L2: manual-anchor single rect vs
    multi-entity GT FAILs via §8.3.3 (no normalized rescue)."""
    plan = make_single_rect_plan()
    plan["scale"]["anchor"] = {
        "type": "manual", "ocr_text": "", "real_length_mm": 1.0,
        "px_length": 4.0, "confidence": 0.0,
    }
    plan["scale"]["uncertain"] = True
    plan["texts_masked"] = []
    report = verify_plan(plan, make_gt(), level="L2")
    assert report["verdict"] == VERDICT_FAIL
    assert any("manual_anchor" in h for h in report["hard_fails"])
    assert all(e["gate"] == "absolute" for e in report["per_loop"])


def test_solved_anchor_l1_stays_absolute_track():
    """Dimension anchor on L1: behaviour bit-identical to t5 (absolute
    gate, iou_normalized None)."""
    plan = make_plan()
    plan["loops"] = [plan["loops"][0]]
    plan["ribs"] = []
    gt = {"loops": [{"id": "outer_0", "role": "outer",
                     "points": copy.deepcopy(OUTER_POINTS)}], "ribs": []}
    report = verify_plan(plan, gt, level="L1")
    assert report["verdict"] == VERDICT_PASS
    entry = report["per_loop"][0]
    assert entry["gate"] == "absolute"
    assert entry["iou_normalized"] is None
    assert entry["iou"] >= 0.90


def test_dimension_spoof_still_fails_unchanged():
    report = verify_plan(make_single_rect_plan(), make_gt())
    assert report["verdict"] == VERDICT_FAIL
    assert any("single_outer_spoof" in h for h in report["hard_fails"])
