"""Plan v0.2 loading, hand-rolled schema validation, and v0.1 compat.

Mirrors docs/plan-v02.schema.json without a third-party validator so the
pipeline runs on a bare interpreter. Raises :class:`PlanError` on any
contract violation.
"""

from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timezone


class PlanError(ValueError):
    """Raised when a plan violates the v0.2 contract."""


LOOP_ROLES = ("outer", "hole", "notch", "detail")
ANCHOR_TYPES = ("dimension", "bar", "manual")


def _fail(msg: str) -> PlanError:
    return PlanError(msg)


def validate_plan(plan: dict) -> dict:
    """Validate a v0.2 plan in place-shape; returns the same dict.

    Checks every machine-testable rule of docs/plan-v02.schema.json plus
    §4.2 D4 (hole-area monotonicity) and the exactly-one-outer rule.
    Winding/closure/self-intersection live in the verifier (they produce
    per-loop verdicts, not load errors), except the hard ``closed`` flag.
    """
    if not isinstance(plan, dict):
        raise _fail("plan must be an object")
    for key in ("version", "units", "image", "scale", "loops", "ribs", "texts_masked"):
        if key not in plan:
            raise _fail(f"missing required field: {key}")
    if plan["version"] != "0.2":
        raise _fail(f"version must be '0.2', got {plan['version']!r}")
    if plan["units"] != "mm":
        raise _fail(f"units must be 'mm', got {plan['units']!r}")

    img = plan["image"]
    if not isinstance(img, dict):
        raise _fail("image must be an object")
    for key in ("width_px", "height_px", "source"):
        if key not in img:
            raise _fail(f"image.{key} missing")
    if not (isinstance(img["width_px"], int) and img["width_px"] >= 1):
        raise _fail("image.width_px must be a positive int")
    if not (isinstance(img["height_px"], int) and img["height_px"] >= 1):
        raise _fail("image.height_px must be a positive int")
    if not (isinstance(img["source"], str) and img["source"]):
        raise _fail("image.source must be a non-empty string")

    scale = plan["scale"]
    if not isinstance(scale, dict):
        raise _fail("scale must be an object")
    for key in ("px_per_mm", "anchor", "uncertain"):
        if key not in scale:
            raise _fail(f"scale.{key} missing")
    if not (isinstance(scale["px_per_mm"], (int, float)) and scale["px_per_mm"] > 0):
        raise _fail("scale.px_per_mm must be > 0")
    if not isinstance(scale["uncertain"], bool):
        raise _fail("scale.uncertain must be bool")
    anchor = scale["anchor"]
    if not isinstance(anchor, dict):
        raise _fail("scale.anchor must be an object")
    for key in ("type", "real_length_mm", "px_length", "confidence"):
        if key not in anchor:
            raise _fail(f"scale.anchor.{key} missing")
    if anchor["type"] not in ANCHOR_TYPES:
        raise _fail(f"scale.anchor.type must be one of {ANCHOR_TYPES}")
    if not (isinstance(anchor["real_length_mm"], (int, float)) and anchor["real_length_mm"] > 0):
        raise _fail("scale.anchor.real_length_mm must be > 0")
    if not (isinstance(anchor["px_length"], (int, float)) and anchor["px_length"] > 0):
        raise _fail("scale.anchor.px_length must be > 0")
    if not (0.0 <= anchor["confidence"] <= 1.0):
        raise _fail("scale.anchor.confidence must be in [0, 1]")
    if "bbox_px" in anchor and anchor["bbox_px"] is not None:
        _check_bbox_px(anchor["bbox_px"], "scale.anchor.bbox_px")

    loops = plan["loops"]
    if not isinstance(loops, list) or len(loops) < 1:
        raise _fail("loops must be a non-empty array")
    seen_ids: set[str] = set()
    outer_count = 0
    for loop in loops:
        _check_loop_shape(loop, seen_ids)
        if loop["role"] == "outer":
            outer_count += 1
    if outer_count != 1:
        raise _fail(f"loops must contain exactly 1 outer, got {outer_count}")
    _check_area_monotonicity(loops)

    ribs = plan["ribs"]
    if not isinstance(ribs, list):
        raise _fail("ribs must be an array")
    seen_rib_ids: set[str] = set()
    for rib in ribs:
        _check_rib_shape(rib, seen_rib_ids)

    texts = plan["texts_masked"]
    if not isinstance(texts, list):
        raise _fail("texts_masked must be an array")
    for item in texts:
        if not isinstance(item, dict):
            raise _fail("texts_masked items must be objects")
        for key in ("text", "bbox_px", "used_as_anchor"):
            if key not in item:
                raise _fail(f"texts_masked item missing {key}")
        if not isinstance(item["text"], str):
            raise _fail("texts_masked.text must be a string")
        _check_bbox_px(item["bbox_px"], "texts_masked.bbox_px")
        if not isinstance(item["used_as_anchor"], bool):
            raise _fail("texts_masked.used_as_anchor must be bool")

    return plan


def _check_bbox_px(bbox, where: str) -> None:
    if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4
            or not all(isinstance(v, (int, float)) for v in bbox)):
        raise _fail(f"{where} must be [x0, y0, x1, y1] numbers")
    x0, y0, x1, y1 = bbox
    if not (x1 > x0 and y1 > y0):
        raise _fail(f"{where} must satisfy x1>x0 and y1>y0")


def _check_loop_shape(loop: dict, seen_ids: set[str]) -> None:
    if not isinstance(loop, dict):
        raise _fail("loops items must be objects")
    for key in ("id", "role", "points", "closed", "area_mm2", "confidence", "source"):
        if key not in loop:
            raise _fail(f"loop missing {key}")
    if not isinstance(loop["id"], str) or not loop["id"]:
        raise _fail("loop.id must be a non-empty string")
    if loop["id"] in seen_ids:
        raise _fail(f"duplicate loop id: {loop['id']}")
    seen_ids.add(loop["id"])
    if loop["role"] not in LOOP_ROLES:
        raise _fail(f"loop role must be one of {LOOP_ROLES}")
    pts = loop["points"]
    if not isinstance(pts, list) or len(pts) < 3:
        raise _fail(f"loop {loop['id']}: points need >=3 entries")
    for p in pts:
        if (not isinstance(p, (list, tuple)) or len(p) != 2
                or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in p)):
            raise _fail(f"loop {loop['id']}: each point must be [x_mm, y_mm] finite numbers")
    if loop["closed"] is not True:
        raise _fail(f"loop {loop['id']}: closed must be true (D2)")
    if not (isinstance(loop["area_mm2"], (int, float)) and loop["area_mm2"] > 0):
        raise _fail(f"loop {loop['id']}: area_mm2 must be > 0")
    if not (0.0 <= loop["confidence"] <= 1.0):
        raise _fail(f"loop {loop['id']}: confidence must be in [0, 1]")
    if not (isinstance(loop["source"], str) and loop["source"]):
        raise _fail(f"loop {loop['id']}: source must be a non-empty string")


def _check_area_monotonicity(loops: list) -> None:
    """D4: total hole area must stay below 50% of the outer area."""
    from .geometry import polygon_area  # local import: geometry has no plan dep

    outer_area = None
    hole_area = 0.0
    for loop in loops:
        area = polygon_area(loop["points"])
        if loop["role"] == "outer":
            outer_area = area
        elif loop["role"] == "hole":
            hole_area += area
    if outer_area is not None and outer_area > 0 and hole_area >= 0.5 * outer_area:
        raise _fail(
            f"hole area {hole_area:.2f} >= 50% of outer {outer_area:.2f} (D4)"
        )


def _check_rib_shape(rib: dict, seen_ids: set[str]) -> None:
    if not isinstance(rib, dict):
        raise _fail("ribs items must be objects")
    for key in ("id", "centerline", "width_mm", "extends_mm", "confidence"):
        if key not in rib:
            raise _fail(f"rib missing {key}")
    if not isinstance(rib["id"], str) or not rib["id"]:
        raise _fail("rib.id must be a non-empty string")
    if rib["id"] in seen_ids:
        raise _fail(f"duplicate rib id: {rib['id']}")
    seen_ids.add(rib["id"])
    cl = rib["centerline"]
    if not isinstance(cl, list) or len(cl) < 2:
        raise _fail(f"rib {rib['id']}: centerline needs >=2 points")
    for p in cl:
        if (not isinstance(p, (list, tuple)) or len(p) != 2
                or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in p)):
            raise _fail(f"rib {rib['id']}: centerline points must be [x_mm, y_mm]")
    if not (isinstance(rib["width_mm"], (int, float)) and rib["width_mm"] > 0):
        raise _fail(f"rib {rib['id']}: width_mm must be > 0")
    ext = rib["extends_mm"]
    if (not isinstance(ext, (list, tuple)) or len(ext) != 2
            or not all(isinstance(v, (int, float)) and v >= 0 for v in ext)):
        raise _fail(f"rib {rib['id']}: extends_mm must be [>=0, >=0]")
    if not (0.0 <= rib["confidence"] <= 1.0):
        raise _fail(f"rib {rib['id']}: confidence must be in [0, 1]")


def upgrade_v01(old: dict) -> dict:
    """§4.5 rule 1: read v0.1, return an equivalent v0.2 plan.

    ``polygon`` becomes the single outer loop; the hand-filled scale becomes
    a ``manual`` anchor with ``uncertain=true`` (which §8.3.3 fails on L2/L3).
    """
    if not isinstance(old, dict):
        raise _fail("v0.1 plan must be an object")
    if "polygon" not in old:
        raise _fail("v0.1 plan needs 'polygon'")
    from .geometry import polygon_area  # local import, see above

    polygon = [[float(x), float(y)] for x, y in old["polygon"]]
    px_per_mm = float(old.get("scale_px_per_mm", 3.78))
    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "version": "0.2",
        "units": "mm",
        "image": {"width_px": 800, "height_px": 600, "source": old.get("source", "v01-upgrade")},
        "scale": {
            "px_per_mm": px_per_mm,
            "anchor": {
                "type": "manual",
                "ocr_text": "",
                "real_length_mm": 1.0,
                "px_length": px_per_mm,
                "confidence": 0.0,
            },
            "uncertain": True,
        },
        "loops": [{
            "id": "outer_0",
            "role": "outer",
            "points": polygon,
            "closed": True,
            "area_mm2": polygon_area(polygon),
            "confidence": 0.5,
            "source": "v01-upgrade",
        }],
        "ribs": [],
        "texts_masked": [],
        "meta": {"tracer": "v01-upgrade", "created_at": now,
                 "notes": "upgraded from v0.1; L2/L3 must FAIL per §8.3.3"},
    }
    return validate_plan(plan)


def load_plan(path_or_dict) -> dict:
    """Load from a JSON file path or dict; auto-upgrades v0.1; validates."""
    if isinstance(path_or_dict, dict):
        plan = copy.deepcopy(path_or_dict)
    elif isinstance(path_or_dict, str):
        with open(path_or_dict, "r", encoding="utf-8") as fh:
            plan = json.load(fh)
    else:
        raise _fail("load_plan needs a dict or a JSON file path")
    version = plan.get("version", "0.1")
    if version == "0.1" or ("polygon" in plan and "loops" not in plan):
        return upgrade_v01(plan)
    return validate_plan(plan)


def dump_plan(plan: dict, path: str) -> str:
    validate_plan(plan)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)
    return path
