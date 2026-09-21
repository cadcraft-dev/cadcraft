"""缝合（stitch）：多矩形 / 多边形碎片合并。

两条诚实路径（均无偏，不靠大包围盒糊弄）：
- ``stitch_rects``：矩形精确合并——gap 容差内相接/交叠的矩形做 bbox 并集。
  适用于“多矩形检测器”输出的碎片。
- ``bridge_gaps`` + 重标记：多边形碎片缝合 = 闭运算桥接断线（morph.close，
  膨胀后腐蚀回来，尺寸无偏），再由 components 重新标记/提取。
- ``union_outlines``：实际交叠/相接的多边形做栅格精确并集 + 重提轮廓
  （只合并真实相连部分，不桥接空白；桥接请用 bridge_gaps）。
"""

from __future__ import annotations

from . import morph as _morph
from .components import extract_loops


def _gap(a0, a1, b0, b1) -> float:
    """一维区间间隙（≤0 表示交叠/相接）。"""
    return max(a0, b0) - min(a1, b1)


def rects_touch(r1, r2, gap_tol: float) -> bool:
    """两矩形 [x0,y0,x1,y1] 在 gap_tol 内相接/交叠（两轴同时满足）。"""
    return _gap(r1[0], r1[2], r2[0], r2[2]) <= gap_tol and \
        _gap(r1[1], r1[3], r2[1], r2[3]) <= gap_tol


def stitch_rects(rects, gap_tol: float = 2.0):
    """矩形缝合：gap 容差传递闭包合并，输出合并后矩形（输入顺序无关，输出按 x0,y0 排序）。"""
    rects = [[float(v) for v in r] for r in rects]
    parent = list(range(len(rects)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if rects_touch(rects[i], rects[j], gap_tol):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)
    groups = {}
    for i, r in enumerate(rects):
        groups.setdefault(find(i), []).append(r)
    merged = []
    for rs in groups.values():
        merged.append([min(r[0] for r in rs), min(r[1] for r in rs),
                       max(r[2] for r in rs), max(r[3] for r in rs)])
    return sorted(merged)


def bridge_gaps(binary, radius_px: int):
    """多边形碎片缝合：闭运算桥接 ≤2r 缺口（无偏），返回新二值图。"""
    return _morph.close(binary, int(radius_px))


def rect_of_points(points_px):
    xs = [p[0] for p in points_px]
    ys = [p[1] for p in points_px]
    return [min(xs), min(ys), max(xs), max(ys)]


def union_outlines(polygons_px, width: int, height: int, rdp_eps: float = 0.6):
    """栅格精确并集 + 重提轮廓。返回合并后的 loop 列表（extract_loops 格式，角色未分配）。

    只合并真实相连部分；断线桥接是 bridge_gaps 的职责，不在此。
    """
    from .geometry import rasterize_polygon

    canvas = [[0] * width for _ in range(height)]
    for poly in polygons_px:
        for x, y in rasterize_polygon(poly, width, height):
            canvas[y][x] = 1
    loops, _ = extract_loops(canvas, rdp_eps=rdp_eps, min_loop_area_px=1.0,
                             min_hole_area_px=1.0)
    return loops

# ---- v0.1 text-path (kept for examples/text_to_dxf + trace_image) ----
"""P1: segments + OCR texts -> Plan (rules v0.1 + sanity guard)."""
import re
from ..planner.schema import Plan, PlanParam, PlanStep

def _sane(v: float) -> bool:
    return v is not None and 0.5 <= float(v) <= 10000

def stitch_to_plan(vec: dict, ocr_texts: list[str], scale_px_per_mm: float = 5.0) -> Plan:
    joined = " ".join(ocr_texts)
    m = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)", joined)
    dia = re.search(r"(?:Phi|P[hH]i|Φ|φ|DI?A?)\s*(\d+(?:\.\d+)?)", joined, re.I)
    # hi20 这种Phi误识也兜一下: 裸的 \d+ 在圆存在时可疑
    if not dia:
        m2 = re.search(r"[hiIl]{1,2}\s*(\d+(?:\.\d+)?)", joined)
        if m2 and vec.get("circles"):
            dia = m2
    rfil = re.search(r"R\s*(\d+(?:\.\d+)?)", joined)
    L = W = None
    if m and _sane(float(m.group(1))) and _sane(float(m.group(2))):
        L, W = float(m.group(1)), float(m.group(2))
    elif vec.get("rect_fit"):
        _, _, w, h = vec["rect_fit"]["bbox"]
        L, W = round(w / scale_px_per_mm, 2), round(h / scale_px_per_mm, 2)
    else:
        L, W = 80.0, 50.0
    # 0值/极小值保护: OCR把80认成0时直接丢弃用像素估计
    if not (_sane(L) and _sane(W)):
        if vec.get("rect_fit"):
            _, _, w, h = vec["rect_fit"]["bbox"]
            L, W = round(w / scale_px_per_mm, 2), round(h / scale_px_per_mm, 2)
        else:
            L, W = 80.0, 50.0
    params: dict[str, PlanParam] = {"L1": PlanParam("L1", float(L)), "W1": PlanParam("W1", float(W))}
    steps: list[PlanStep] = [PlanStep(op="rect", params={"x": 0, "y": 0, "w": "L1", "h": "W1"})]
    D = float(dia.group(1)) if (dia and _sane(float(dia.group(1)))) else None
    if D is None and vec.get("circles"):
        c = vec["circles"][0]
        D = round(c["r"]*2/scale_px_per_mm, 2)
    if D and _sane(D):
        params["D1"] = PlanParam("D1", float(D))
        steps.append(PlanStep(op="hole_center_rect", params={"d": "D1"}))
    return Plan(units="mm", params=params, steps=steps,
                notes=f"stitched vec({vec.get('count',0)} segs,{len(vec.get('circles',[]))} circles)+ocr{ocr_texts[:5]} scale={scale_px_per_mm}px/mm")
