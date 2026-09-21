"""Verifier hardening tests (t3, anti-R5): per-loop gates + hard fails.

Covers spec §7 (per-loop IoU / rib / scale / D2–D4) and §8.3 (five
anti-spoof rules incl. the single-rectangle negative control), plus L1
no-regression and report-conformance (§8.3.4).
"""

import copy

import pytest

from cadcraft import geometry as G
from cadcraft.plan_io import load_plan, upgrade_v01
from cadcraft.verifier.verifier import (
    VERDICT_FAIL,
    VERDICT_PASS,
    check_report_conformance,
    verify_plan,
)

from helpers_v02 import (
    HOLE_POINTS,
    OUTER_POINTS,
    make_gt,
    make_plan,
    make_single_rect_plan,
)


# --- honest cases --------------------------------------------------------


def test_honest_bracket_passes_with_full_detail():
    report = verify_plan(make_plan(), make_gt())
    assert report["verdict"] == VERDICT_PASS
    assert report["recall"] == pytest.approx(1.0)
    assert {e["gt_id"] for e in report["per_loop"]} == {"outer_0", "hole_0"}
    assert all(e["matched"] for e in report["per_loop"])
    assert all(e["iou"] >= 0.90 for e in report["per_loop"])
    assert report["ribs"] and report["ribs"][0]["recalled"]
    assert report["scale_error_pct"] == pytest.approx(0.0)
    assert report["hard_fails"] == []
    # bbox advisory is recorded but never decisive …
    assert report["bbox_iou_advisory"] is not None
    ok, problems = check_report_conformance(report)
    assert ok, problems


def test_notch_case_passes():
    report = verify_plan(make_plan(loops="outer+hole+notch"), make_gt(with_notch=True))
    assert report["verdict"] == VERDICT_PASS
    assert len(report["per_loop"]) == 3
    assert all(e["matched"] for e in report["per_loop"])


def test_l1_single_loop_no_regression():
    """v0.1 upgraded single-rectangle plan still passes L1 (shape-only)."""
    gt = {"loops": [{"id": "outer_0", "role": "outer",
                     "points": copy.deepcopy(OUTER_POINTS)}],
          "ribs": [],
          "key_dimensions": [{"id": "k", "loop_id": "outer_0",
                              "edge": [0, 1], "length_mm": 120.0}]}
    plan = make_plan()
    plan["loops"] = [plan["loops"][0]]  # outer only
    plan["ribs"] = []
    report = verify_plan(plan, gt, level="L1")
    assert report["verdict"] == VERDICT_PASS
    assert report["level"] == "L1"


def test_v01_upgrade_passes_l1_but_fails_l2():
    old = {"version": "0.1", "units": "mm", "scale_px_per_mm": 4.0,
           "polygon": copy.deepcopy(OUTER_POINTS)}
    plan = load_plan(old)  # auto-upgrade path
    assert plan["scale"]["anchor"]["type"] == "manual"
    assert plan["scale"]["uncertain"] is True
    gt1 = {"loops": [{"id": "outer_0", "role": "outer",
                      "points": copy.deepcopy(OUTER_POINTS)}], "ribs": []}
    assert verify_plan(plan, gt1, level="L1")["verdict"] == VERDICT_PASS
    l2 = verify_plan(plan, make_gt(), level="L2")
    assert l2["verdict"] == VERDICT_FAIL
    assert any("manual_anchor" in h for h in l2["hard_fails"])


# --- §8.3 negative controls (each must FAIL) -------------------------------


def test_single_rectangle_spoof_fails_despite_high_bbox_iou():
    """The R5 hole: bbox-IoU of the spoof is high, verdict still FAIL."""
    plan = make_single_rect_plan()
    gt = make_gt()
    spoof_bbox = G.bbox_of(plan["loops"][0]["points"])
    gt_bbox = G.bbox_of(OUTER_POINTS)
    assert G.bbox_iou(spoof_bbox, gt_bbox) > 0.80  # the old gate would pass
    report = verify_plan(plan, gt)
    assert report["verdict"] == VERDICT_FAIL
    assert any("single_outer_spoof" in h for h in report["hard_fails"])
    assert any("ribs_empty" in h for h in report["hard_fails"])
    assert report["recall"] < 0.80


def test_missing_rib_fails():
    report = verify_plan(make_plan(rib=False), make_gt())
    assert report["verdict"] == VERDICT_FAIL
    assert any("ribs_empty" in h for h in report["hard_fails"])


def test_manual_anchor_fails_l2():
    report = verify_plan(make_plan(anchor_type="manual"), make_gt(), level="L2")
    assert report["verdict"] == VERDICT_FAIL
    assert any("manual_anchor" in h for h in report["hard_fails"])


def test_flipped_hole_winding_fails():
    report = verify_plan(make_plan(anchor_type="flip-hole"), make_gt())
    assert report["verdict"] == VERDICT_FAIL
    hole_entry = next(e for e in report["per_loop"] if e["gt_id"] == "hole_0")
    assert not hole_entry["matched"]
    assert any("loop_invalid" in r for r in report["reasons"])


def test_scaled_plan_fails_scale_gate():
    """5 % oversize: shape IoU may stay decent, absolute check kills it."""
    report = verify_plan(make_plan(scale_factor=1.05), make_gt())
    assert report["verdict"] == VERDICT_FAIL
    assert any("scale_gate" in h for h in report["hard_fails"])
    assert report["scale_error_pct"] == pytest.approx(5.0)


def test_fabricated_anchor_crosscheck_fails():
    """Anchor bbox with no equal texts_masked entry → FAIL (§6)."""
    plan = make_plan()
    plan["texts_masked"][0]["bbox_px"] = [0, 0, 10, 10]
    report = verify_plan(plan, make_gt())
    assert report["verdict"] == VERDICT_FAIL
    assert any("anchor_crosscheck" in h for h in report["hard_fails"])


def test_self_intersecting_loop_fails():
    plan = make_plan()
    plan["loops"][0]["points"] = [[0, 0], [120, 0], [0, 80], [120, 80]]
    plan["loops"][0]["area_mm2"] = 100.0
    report = verify_plan(plan, make_gt())
    assert report["verdict"] == VERDICT_FAIL
    assert any("loop_invalid" in r for r in report["reasons"])


def test_d4_hole_dump_truck_fails_at_load():
    """Hole bigger than half the outer is plan-illegal (§4.2 D4)."""
    plan = make_plan()
    plan["loops"][1]["points"] = [[-10, -10], [-10, 90], [130, 90], [130, -10]]
    plan["loops"][1]["area_mm2"] = 14000.0
    report = verify_plan(plan, make_gt())
    assert report["verdict"] == VERDICT_FAIL
    assert any("plan_invalid" in r for r in report["reasons"])


# --- §8.3.4 report conformance ----------------------------------------------


def test_legacy_bbox_only_report_is_nonconformant():
    legacy = {"bbox_iou": 0.95, "passed": True}
    ok, problems = check_report_conformance(legacy)
    assert not ok
    assert any("per_loop" in p for p in problems)


def test_bbox_iou_alone_never_passes():
    """Even a perfect bbox number cannot produce a PASS without detail."""
    ok, _ = check_report_conformance({"verdict": "PASS"})
    assert not ok


def test_rib_width_error_fails_rib():
    plan = make_plan()
    plan["ribs"][0]["width_mm"] = 9.0  # +50 % over GT 6.0
    report = verify_plan(plan, make_gt())
    assert report["verdict"] == VERDICT_FAIL
    assert not report["ribs"][0]["recalled"]
