"""t4 单测：scale solver（spec §5 D5 最长 OCR 反推 + §6 交叉检查）。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cadcraft.tracing.scale_solver import (  # noqa: E402
    parse_dimension_text,
    px_to_mm,
    solve_scale,
    verify_anchor_consistency,
)


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("120", 120.0),
        ("120mm", 120.0),
        ("120 MM", 120.0),
        ("12cm", 120.0),
        ("1.2m", 1200.0),
        ("Ø20", 20.0),
        ("Φ20", 20.0),
        ("R10", 10.0),
        ("M10", 10.0),
        ("  60  ", 60.0),
        ("ABC", None),
        ("", None),
        ("0", None),
        ("-5", None),
        ("12.5.6", None),
    ],
)
def test_parse_dimension_text(text, want):
    assert parse_dimension_text(text) == want


def test_longest_wins_spec_example():
    out = solve_scale(
        [
            {"text": "60", "bbox_px": [100, 700, 340, 740], "px_length": 240.0, "confidence": 0.9},
            {"text": "120", "bbox_px": [100, 800, 580, 840], "px_length": 480.0, "confidence": 0.93},
        ],
        1200,
        900,
    )
    scale, masked = out["scale"], out["texts_masked"]
    assert scale["px_per_mm"] == pytest.approx(4.0)
    assert scale["uncertain"] is False
    assert scale["anchor"]["type"] == "dimension"
    assert scale["anchor"]["ocr_text"] == "120"
    assert scale["anchor"]["bbox_px"] == [100.0, 800.0, 580.0, 840.0]
    winners = [m for m in masked if m["used_as_anchor"]]
    assert len(winners) == 1 and winners[0]["text"] == "120"
    ok, _ = verify_anchor_consistency(scale, masked)
    assert ok


def test_low_confidence_longest_is_skipped():
    out = solve_scale(
        [
            {"text": "120", "bbox_px": [100, 800, 580, 840], "px_length": 480.0, "confidence": 0.3},
            {"text": "60", "bbox_px": [100, 700, 340, 740], "px_length": 240.0, "confidence": 0.9},
        ],
        1200,
        900,
    )
    assert out["scale"]["anchor"]["ocr_text"] == "60"
    assert out["scale"]["px_per_mm"] == pytest.approx(4.0)


def test_empty_ocr_manual_fallback():
    out = solve_scale([], 1200, 900)
    assert out["scale"]["uncertain"] is True
    assert out["scale"]["anchor"]["type"] == "manual"
    assert out["texts_masked"] == []
    ok, _ = verify_anchor_consistency(out["scale"], out["texts_masked"])
    assert ok


def test_tampered_anchor_fails_cross_check():
    out = solve_scale(
        [{"text": "120", "bbox_px": [100, 800, 580, 840], "px_length": 480.0, "confidence": 0.93}],
        1200,
        900,
    )
    bad_scale = {
        "px_per_mm": 9.99,
        "uncertain": False,
        "anchor": dict(out["scale"]["anchor"], px_length=999.0,
                       bbox_px=[0.0, 0.0, 999.0, 999.0]),
    }
    ok, reason = verify_anchor_consistency(bad_scale, out["texts_masked"])
    assert not ok and "编造" in reason


def test_degenerate_bbox_raises():
    with pytest.raises(ValueError):
        solve_scale(
            [{"text": "120", "bbox_px": [5, 5, 5, 5], "px_length": 480.0, "confidence": 0.9}],
            1200,
            900,
        )


def test_px_to_mm_cad_axes():
    scale = {"px_per_mm": 4.0}
    assert px_to_mm(480.0, 900.0 - 0.0, scale, 900) == pytest.approx((120.0, 0.0))
    assert px_to_mm(0.0, 0.0, scale, 900) == pytest.approx((0.0, 225.0))


def test_output_fits_plan_io_validator():
    """t4→t3/t5 集成：我的 scale+texts_masked 节点必须过 plan_io.validate_plan。"""
    from cadcraft.plan_io import validate_plan

    out = solve_scale(
        [{"text": "120", "bbox_px": [100, 800, 580, 840], "px_length": 480.0, "confidence": 0.93}],
        1200,
        900,
    )
    plan = {
        "version": "0.2",
        "units": "mm",
        "image": {"width_px": 1200, "height_px": 900, "source": "level2_bracket.png"},
        "scale": out["scale"],
        "loops": [{
            "id": "outer_0", "role": "outer",
            "points": [[0, 0], [120, 0], [120, 40], [40, 40], [40, 80], [0, 80]],
            "closed": True, "area_mm2": 6400.0, "confidence": 0.95, "source": "stitched",
        }],
        "ribs": [{
            "id": "rib_0", "centerline": [[40, 40], [80, 40]],
            "width_mm": 6.0, "extends_mm": [0.0, 0.0], "confidence": 0.85,
        }],
        "texts_masked": out["texts_masked"],
    }
    assert validate_plan(plan) is plan
