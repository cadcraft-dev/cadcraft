"""Pure-python planar geometry for the v0.2 verifier.

No third-party dependency (numpy only): polygon signed area, winding,
closure, self-intersection, Sutherland-free raster IoU that is exact for
concave rings (L-shapes, notches), bbox IoU, polyline metrics.

All coordinates are CAD mm (x right, y up).
"""

from __future__ import annotations

import math

import numpy as np

CLOSURE_TOL_MM = 0.05
LOOP_IOU_PASS = 0.90
RIB_ENDPOINT_TOL_MM = 1.0
RIB_WIDTH_REL_TOL = 0.20
SCALE_REL_TOL = 0.02


def signed_area(points) -> float:
    """Shoelace signed area. >0 means CCW, <0 means CW."""
    pts = np.asarray(points, dtype=float)
    if len(pts) < 3:
        return 0.0
    x = pts[:, 0]
    y = pts[:, 1]
    return float(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def is_ccw(points) -> bool:
    return signed_area(points) > 0.0


def ring_closed(points, tol: float = CLOSURE_TOL_MM) -> bool:
    """Explicit-repeat closure: first ≈ last within tol.

    Writers may also emit implicit rings (last != first, edge wraps);
    those are closed by definition — see ``loop_closure_ok``.
    """
    pts = np.asarray(points, dtype=float)
    if len(pts) < 2:
        return False
    return bool(np.hypot(pts[0, 0] - pts[-1, 0], pts[0, 1] - pts[-1, 1]) <= tol)


def _ring_vertices(points):
    """Vertices with a duplicated closing point removed."""
    pts = np.asarray(points, dtype=float)
    if len(pts) > 1 and np.hypot(pts[0, 0] - pts[-1, 0], pts[0, 1] - pts[-1, 1]) <= CLOSURE_TOL_MM:
        pts = pts[:-1]
    return pts


def loop_closure_ok(loop: dict) -> tuple[bool, str]:
    pts = np.asarray(loop.get("points", []), dtype=float)
    if len(pts) < 3:
        return False, f"loop {loop.get('id')}: need >=3 points, got {len(pts)}"
    if not bool(loop.get("closed", False)):
        return False, f"loop {loop.get('id')}: closed must be true (D2)"
    verts = _ring_vertices(pts)
    if len(verts) < 3:
        return False, f"loop {loop.get('id')}: degenerate after de-duplication"
    return True, ""


def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, c) -> bool:
    return (min(a[0], c[0]) - 1e-9 <= b[0] <= max(a[0], c[0]) + 1e-9 and
            min(a[1], c[1]) - 1e-9 <= b[1] <= max(a[1], c[1]) + 1e-9)


def _segments_intersect(p1, p2, p3, p4) -> bool:
    d1 = _orientation(p3, p4, p1)
    d2 = _orientation(p3, p4, p2)
    d3 = _orientation(p1, p2, p3)
    d4 = _orientation(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    if abs(d1) <= 1e-9 and _on_segment(p3, p1, p4):
        return True
    if abs(d2) <= 1e-9 and _on_segment(p3, p2, p4):
        return True
    if abs(d3) <= 1e-9 and _on_segment(p1, p3, p2):
        return True
    if abs(d4) <= 1e-9 and _on_segment(p1, p4, p2):
        return True
    return False


def has_self_intersection(points) -> bool:
    """True when a non-adjacent edge pair crosses (figure-eight etc.)."""
    verts = _ring_vertices(points)
    n = len(verts)
    if n < 4:
        return False
    edges = [(verts[i], verts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if abs(i - j) <= 1 or (i == 0 and j == n - 1):
                continue  # adjacent edges share a vertex by construction
            if _segments_intersect(edges[i][0], edges[i][1], edges[j][0], edges[j][1]):
                return True
    return False


def winding_ok(loop: dict) -> tuple[bool, str]:
    """D3: outer must be CCW, hole must be CW. notch/detail unchecked."""
    role = loop.get("role")
    if role not in ("outer", "hole"):
        return True, ""
    area = signed_area(loop.get("points", []))
    if role == "outer" and area <= 0:
        return False, f"loop {loop.get('id')}: outer must be CCW (signed area >0), got {area:.4f}"
    if role == "hole" and area >= 0:
        return False, f"loop {loop.get('id')}: hole must be CW (signed area <0), got {area:.4f}"
    return True, ""


def polygon_area(points) -> float:
    return abs(signed_area(points))


def bbox_of(points):
    pts = np.asarray(points, dtype=float)
    return [float(pts[:, 0].min()), float(pts[:, 1].min()),
            float(pts[:, 0].max()), float(pts[:, 1].max())]


def bbox_iou(a, b) -> float:
    """Axis-aligned bbox IoU. ADVISORY ONLY — never a pass criterion (D7)."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    aa = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    bb = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = aa + bb - inter
    return inter / union if union > 0 else 0.0


def _points_in_polygon(xs: np.ndarray, ys: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Vectorized ray-casting point-in-polygon (works for concave rings)."""
    inside = np.zeros(xs.shape, dtype=bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cond = ((y1 > ys) != (y2 > ys)) & (
            xs < (x2 - x1) * (ys - y1) / (y2 - y1 + 1e-12) + x1
        )
        inside ^= cond
    return inside


def polygon_mask(points, bounds, cell: float) -> np.ndarray:
    """Rasterize a ring onto a grid over ``bounds`` with ``cell`` mm step."""
    x0, y0, x1, y1 = bounds
    nx = max(1, int(math.ceil((x1 - x0) / cell)))
    ny = max(1, int(math.ceil((y1 - y0) / cell)))
    cx = x0 + (np.arange(nx) + 0.5) * cell
    cy = y0 + (np.arange(ny) + 0.5) * cell
    xx, yy = np.meshgrid(cx, cy)
    return _points_in_polygon(xx.ravel(), yy.ravel(), _ring_vertices(points)).reshape(ny, nx)


def polygon_iou(a_points, b_points, cell: float = 0.25) -> float:
    """True shape IoU in mm space via rasterization (concave-safe).

    Default 0.25 mm cell keeps the quantization error far below the 0.90
    gate for L2-scale parts while staying fast (<1 s for bracket sizes).
    """
    ba = bbox_of(a_points)
    bb = bbox_of(b_points)
    bounds = [min(ba[0], bb[0]), min(ba[1], bb[1]),
              max(ba[2], bb[2]), max(ba[3], bb[3])]
    # Guard against degenerate bounds.
    if bounds[2] - bounds[0] <= 1e-9 or bounds[3] - bounds[1] <= 1e-9:
        return 0.0
    ma = polygon_mask(a_points, bounds, cell)
    mb = polygon_mask(b_points, bounds, cell)
    inter = np.logical_and(ma, mb).sum()
    union = np.logical_or(ma, mb).sum()
    if union == 0:
        return 0.0
    return float(inter) / float(union)


def normalized_points(points):
    """Map a ring to shape space: centroid → origin, max bbox side → 1.

    Translation + uniform-scale invariant; rotation and aspect stay
    visible. Returns None for degenerate (zero-size) rings.
    """
    verts = _ring_vertices(points).astype(float)
    if len(verts) < 3:
        return None
    bb = bbox_of(verts)
    s = max(bb[2] - bb[0], bb[3] - bb[1])
    if s <= 1e-12:
        return None
    return (verts - verts.mean(axis=0)) / s


def normalized_iou(a_points, b_points, cell: float = 0.005) -> float:
    """Shape-only IoU in normalized space (t6/N1: manual-L1 gate).

    Same raster engine as :func:`polygon_iou`, but both rings are first
    passed through :func:`normalized_points`, so a pure scale error
    (fallback S) cannot sink the score while aspect/rotation errors still
    do. Cell 0.005 on a unit-max-side shape ≈ 200 cells per side,
    quantization far below the 0.90 gate.
    """
    na = normalized_points(a_points)
    nb = normalized_points(b_points)
    if na is None or nb is None:
        return 0.0
    return polygon_iou(na, nb, cell=cell)


def polyline_length(points) -> float:
    pts = np.asarray(points, dtype=float)
    if len(pts) < 2:
        return 0.0
    return float(np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1])).sum())


def segment_length(a, b) -> float:
    return float(math.hypot(a[0] - b[0], a[1] - b[1]))
