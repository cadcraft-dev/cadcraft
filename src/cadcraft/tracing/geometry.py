"""多边形几何工具（纯标准库）：面积/环绕/包含/RDP/光栅化/IoU。

坐标约定：像素系浮点（y 向下）或 CAD 系（y 向上）均为 [x, y] 点列，
本模块只做纯几何运算，不感知坐标系方向（有向面积符号由调用方解释）。
"""

from __future__ import annotations

import math


def signed_area(points) -> float:
    """鞋带公式有向面积。像素系 y 向下时：>0 为顺时针。"""
    pts = list(points)
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def ensure_winding(points, ccw: bool, y_down: bool = False):
    """强制环绕方向。ccw=True 要求逆时针（数学系）；像素系 y 向下时符号取反。"""
    pts = [list(p) for p in points]
    area = signed_area(pts)
    if area == 0:
        return pts
    # 数学系 CCW ⇔ area>0；像素系 y 向下时 CCW ⇔ area<0。
    is_ccw = (area > 0) != y_down
    if is_ccw != bool(ccw):
        pts.reverse()
    return pts


def bbox_of_points(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def point_in_polygon(px, py, points) -> bool:
    """射线法；点在边上视为内部（hole 归属判定需要稳定的包含语义）。"""
    pts = list(points)
    n = len(pts)
    inside = False
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        # 点在边上（跨积≈0 且在包围盒内）→ 内部
        cross = (x1 - x0) * (py - y0) - (y1 - y0) * (px - x0)
        if abs(cross) < 1e-9 and min(x0, x1) - 1e-9 <= px <= max(x0, x1) + 1e-9 \
                and min(y0, y1) - 1e-9 <= py <= max(y0, y1) + 1e-9:
            return True
        if (y0 > py) != (y1 > py):
            xinters = x0 + (py - y0) * (x1 - x0) / (y1 - y0)
            if xinters > px:
                inside = not inside
    return inside


def _orient(ax, ay, bx, by, cx, cy) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def segments_intersect(p1, p2, p3, p4) -> bool:
    """线段相交（含端点接触；调用方用它做自交检测，相邻边除外）。"""

    def on_seg(a, b, c):
        return min(a[0], c[0]) - 1e-9 <= b[0] <= max(a[0], c[0]) + 1e-9 and \
            min(a[1], c[1]) - 1e-9 <= b[1] <= max(a[1], c[1]) + 1e-9

    d1 = _orient(*p1, *p2, *p3)
    d2 = _orient(*p1, *p2, *p4)
    d3 = _orient(*p3, *p4, *p1)
    d4 = _orient(*p3, *p4, *p2)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
            ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    if abs(d1) < 1e-9 and on_seg(p1, p3, p2):
        return True
    if abs(d2) < 1e-9 and on_seg(p1, p4, p2):
        return True
    if abs(d3) < 1e-9 and on_seg(p3, p1, p4):
        return True
    if abs(d4) < 1e-9 and on_seg(p3, p2, p4):
        return True
    return False


def is_simple_polygon(points) -> bool:
    """自交检测：O(n²)，tracing 轮廓点数小，可接受；非法则 plan 拒收（spec D2）。"""
    pts = list(points)
    n = len(pts)
    if n < 4:
        return True
    for i in range(n):
        for j in range(i + 1, n):
            if abs(i - j) <= 1 or (i == 0 and j == n - 1):
                continue
            if segments_intersect(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                return False
    return True


def _perp_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    denom = math.hypot(dx, dy)
    if denom == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / denom


def rdp(points, eps: float):
    """Ramer-Douglas-Peucker 折线化简（迭代栈实现）。eps 单位与点列一致。"""
    pts = [list(p) for p in points]
    if len(pts) < 3 or eps <= 0:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        s, e = stack.pop()
        if e - s < 2:
            continue
        dmax, imax = 0.0, -1
        for i in range(s + 1, e):
            d = _perp_dist(pts[i], pts[s], pts[e])
            if d > dmax:
                dmax, imax = d, i
        if dmax > eps:
            keep[imax] = True
            stack.append((s, imax))
            stack.append((imax, e))
    return [pts[i] for i, k in enumerate(keep) if k]


def scanline_fill(points):
    """偶奇规则填充，逐像素中心判定，yield (x, y) 整数像素。"""
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 3:
        return
    y_lo = int(math.floor(min(p[1] for p in pts)))
    y_hi = int(math.ceil(max(p[1] for p in pts)))
    n = len(pts)
    for y in range(y_lo, y_hi + 1):
        yc = y + 0.5
        xs = []
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            if (y0 <= yc < y1) or (y1 <= yc < y0):
                t = (yc - y0) / (y1 - y0)
                xs.append(x0 + t * (x1 - x0))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            x_start = math.ceil(xs[k] - 0.5)
            x_end = math.ceil(xs[k + 1] - 0.5) - 1
            for x in range(x_start, x_end + 1):
                yield (x, y)


def rasterize_polygon(points, width: int, height: int):
    """多边形光栅化为像素集合（限图内；IoU/面积并集 stitch 用）。"""
    out = set()
    for x, y in scanline_fill(points):
        if 0 <= x < width and 0 <= y < height:
            out.add((x, y))
    return out


def sets_iou(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def polygon_perimeter(points) -> float:
    pts = list(points)
    return sum(
        math.hypot(pts[(i + 1) % len(pts)][0] - pts[i][0],
                   pts[(i + 1) % len(pts)][1] - pts[i][1])
        for i in range(len(pts))
    )
