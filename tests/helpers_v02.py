"""Shared v0.2 fixtures: the spec §4.4 L-bracket (outer + hole + rib)."""

import copy

import pytest

OUTER_POINTS = [[0, 0], [120, 0], [120, 40], [40, 40], [40, 80], [0, 80]]  # CCW
HOLE_POINTS = [[15, 15], [15, 25], [25, 25], [25, 15]]  # CW
NOTCH_POINTS = [[120, 40], [132, 40], [132, 52], [120, 52]]  # CCW detail tab
ANCHOR_BBOX = [100, 800, 580, 840]


def make_anchor(atype="dimension"):
    anchor = {
        "type": atype,
        "ocr_text": "120",
        "real_length_mm": 120.0,
        "px_length": 480.0,
        "bbox_px": list(ANCHOR_BBOX),
        "confidence": 0.93,
    }
    if atype == "manual":
        anchor = {
            "type": "manual",
            "ocr_text": "",
            "real_length_mm": 1.0,
            "px_length": 4.0,
            "confidence": 0.0,
        }
    return anchor


def make_plan(*, anchor_type="dimension", loops="outer+hole", rib=True,
              scale_factor=1.0):
    """Honest L-bracket plan. ``loops`` selects outer+hole(+notch)."""
    def sx(pts):
        return [[x * scale_factor, y * scale_factor] for x, y in pts]

    loops_out = [{
        "id": "outer_0", "role": "outer", "points": sx(OUTER_POINTS),
        "closed": True, "area_mm2": 6400.0 * scale_factor ** 2,
        "confidence": 0.95, "source": "stitched",
    }]
    if loops in ("outer+hole", "outer+hole+notch"):
        hole = [p for p in HOLE_POINTS]
        if anchor_type == "flip-hole":
            hole = list(reversed(hole))
        loops_out.append({
            "id": "hole_0", "role": "hole",
            "points": [[x * scale_factor, y * scale_factor] for x, y in hole],
            "closed": True, "area_mm2": 100.0 * scale_factor ** 2,
            "confidence": 0.9, "source": "detected",
        })
    if loops == "outer+hole+notch":
        loops_out.append({
            "id": "notch_0", "role": "notch", "points": sx(NOTCH_POINTS),
            "closed": True, "area_mm2": 144.0 * scale_factor ** 2,
            "confidence": 0.8, "source": "detected",
        })
    ribs = ([{
        "id": "rib_0",
        "centerline": sx([[40, 40], [80, 40]]),
        "width_mm": 6.0, "extends_mm": [0.0, 0.0], "confidence": 0.85,
    }] if rib else [])
    texts = ([{"text": "120", "bbox_px": list(ANCHOR_BBOX),
               "used_as_anchor": True}]
             if anchor_type not in ("manual",) else [])
    anchor = make_anchor("manual" if anchor_type == "manual" else "dimension")
    return {
        "version": "0.2", "units": "mm",
        "image": {"width_px": 1200, "height_px": 900,
                  "source": "level2_bracket.png"},
        "scale": {"px_per_mm": 4.0, "anchor": anchor, "uncertain": False},
        "loops": loops_out, "ribs": ribs, "texts_masked": texts,
        "meta": {"tracer": "t2-stitch", "notes": "fixture"},
    }


def make_gt(*, with_notch=False):
    gt = {
        "loops": [
            {"id": "outer_0", "role": "outer",
             "points": copy.deepcopy(OUTER_POINTS)},
            {"id": "hole_0", "role": "hole",
             "points": copy.deepcopy(HOLE_POINTS)},
        ],
        "ribs": [{"id": "rib_0", "centerline": [[40, 40], [80, 40]],
                  "width_mm": 6.0}],
        "key_dimensions": [
            {"id": "k_outer_width", "loop_id": "outer_0",
             "edge": [0, 1], "length_mm": 120.0},
            {"id": "k_hole_side", "loop_id": "hole_0",
             "edge": [0, 1], "length_mm": 10.0},
        ],
    }
    if with_notch:
        gt["loops"].append(
            {"id": "notch_0", "role": "notch",
             "points": copy.deepcopy(NOTCH_POINTS)})
        gt["key_dimensions"].append(
            {"id": "k_notch", "loop_id": "notch_0",
             "edge": [0, 1], "length_mm": 12.0})
    return gt


def make_single_rect_plan():
    """Negative control: one bounding rectangle pretending to be the bracket."""
    plan = make_plan(rib=False)
    plan["loops"] = [{
        "id": "outer_0", "role": "outer",
        "points": [[0, 0], [120, 0], [120, 80], [0, 80]],
        "closed": True, "area_mm2": 9600.0,
        "confidence": 0.99, "source": "bbox-guess",
    }]
    return plan


@pytest.fixture
def honest_plan():
    return make_plan()


@pytest.fixture
def honest_gt():
    return make_gt()
