"""Multi-loop DXF executor (t3): one v0.2 plan → many DXF entities.

Contract (docs/plan-v02-spec.md §4, §10):

* every loop becomes its own closed ``LWPOLYLINE`` on a role layer —
  ``OUTER`` / ``HOLES`` / ``NOTCH`` / ``DETAIL`` — so no geometry is ever
  merged into a single bounding rectangle (the R1/R5 failure);
* every rib becomes a ``LWPOLYLINE`` centerline on ``RIBS`` carrying its
  ``width_mm`` as constant width;
* masked OCR boxes are exported as audit rectangles on ``TEXT_MASK``
  (never geometry);
* units are millimetres (``$INSUNITS = 4``), coordinates already CAD mm.

Raises :class:`PlanError` for contract-illegal plans (via plan_io).
"""

from __future__ import annotations

import os

from ..plan_io import PlanError, validate_plan

ROLE_LAYERS = {
    "outer": "OUTER",
    "hole": "HOLES",
    "notch": "NOTCH",
    "detail": "DETAIL",
}
RIB_LAYER = "RIBS"
TEXT_MASK_LAYER = "TEXT_MASK"

LAYER_COLORS = {
    "OUTER": 1,      # red
    "HOLES": 3,      # green
    "NOTCH": 30,     # orange-ish
    "DETAIL": 5,     # blue
    "RIBS": 6,       # magenta
    "TEXT_MASK": 8,  # grey
}


def _ensure_layer(doc, name: str) -> None:
    layers = doc.layers
    if name in layers:
        return
    layers.add(name=name, color=LAYER_COLORS.get(name, 7))


def _dedup_close(points):
    """Drop a duplicated closing vertex; ezdxf closes via flag."""
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) > 1:
        x0, y0 = pts[0]
        x1, y1 = pts[-1]
        if abs(x0 - x1) <= 0.05 and abs(y0 - y1) <= 0.05:
            pts = pts[:-1]
    return pts


def plan_to_dxf(plan: dict, path: str) -> dict:
    """Export a validated v0.2 plan to a multi-entity DXF file.

    Returns a summary ``{path, units, loops, ribs, texts, layers}`` where
    ``loops`` maps loop id → ``{layer, vertices}`` and ``ribs`` maps rib
    id → ``{layer, vertices, width_mm}``.
    """
    try:
        import ezdxf
    except ImportError as exc:  # pragma: no cover - env without ezdxf
        raise PlanError("ezdxf is required for DXF export") from exc

    validate_plan(plan)

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # millimetres
    msp = doc.modelspace()

    for layer in list(ROLE_LAYERS.values()) + [RIB_LAYER, TEXT_MASK_LAYER]:
        _ensure_layer(doc, layer)

    summary_loops: dict = {}
    for loop in plan["loops"]:
        layer = ROLE_LAYERS[loop["role"]]
        pts = _dedup_close(loop["points"])
        if len(pts) < 3:
            raise PlanError(f"loop {loop['id']}: degenerate after de-duplication")
        pline = msp.add_lwpolyline(pts, format="xy", close=True)
        pline.dxf.layer = layer
        summary_loops[loop["id"]] = {
            "role": loop["role"],
            "layer": layer,
            "vertices": len(pts),
        }

    summary_ribs: dict = {}
    for rib in plan["ribs"]:
        pts = [(float(x), float(y)) for x, y in rib["centerline"]]
        pline = msp.add_lwpolyline(pts, format="xy", close=False)
        pline.dxf.layer = RIB_LAYER
        pline.dxf.const_width = float(rib["width_mm"])
        summary_ribs[rib["id"]] = {
            "layer": RIB_LAYER,
            "vertices": len(pts),
            "width_mm": float(rib["width_mm"]),
        }

    n_masks = 0
    for item in plan.get("texts_masked", []):
        x0, y0, x1, y1 = (float(v) for v in item["bbox_px"])
        rect = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        pline = msp.add_lwpolyline(rect, format="xy", close=True)
        pline.dxf.layer = TEXT_MASK_LAYER
        n_masks += 1

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    doc.saveas(path)
    return {
        "path": path,
        "units": "mm",
        "loops": summary_loops,
        "ribs": summary_ribs,
        "texts": n_masks,
        "layers": sorted({v["layer"] for v in summary_loops.values()}
                         | {v["layer"] for v in summary_ribs.values()}
                         | ({TEXT_MASK_LAYER} if n_masks else set())),
    }


def read_dxf_summary(path: str) -> dict:
    """Read back a DXF file: count LWPOLYLINE entities per layer.

    Test helper proving the file really holds many entities (anti-R1).
    """
    try:
        import ezdxf
    except ImportError as exc:  # pragma: no cover
        raise PlanError("ezdxf is required to read DXF") from exc
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    per_layer: dict[str, int] = {}
    closed_flags: list[bool] = []
    widths: list[float] = []
    total = 0
    for ent in msp.query("LWPOLYLINE"):
        total += 1
        layer = ent.dxf.layer
        per_layer[layer] = per_layer.get(layer, 0) + 1
        closed_flags.append(bool(ent.closed))
        try:
            widths.append(float(ent.dxf.get("const_width", 0.0) or 0.0))
        except (AttributeError, ValueError, TypeError):
            widths.append(0.0)
    return {
        "path": path,
        "total_lwpolylines": total,
        "per_layer": per_layer,
        "closed_flags": closed_flags,
        "const_widths": widths,
        "insunits": int(doc.header.get("$INSUNITS", 0)),
    }
