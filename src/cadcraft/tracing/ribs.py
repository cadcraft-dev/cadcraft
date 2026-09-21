"""Rib 加强筋提取（spec §4.3）：tophat 残差 → 细长连通域 → 主轴中心线。

- 输入为闭运算后的二值图；tophat 结构元半径 rib_se 应大于筋半宽、小于面板尺寸，
  残差即“比面板细的结构”（筋 / 细线 / 笔画面元边缘——后两者由几何规则滤掉）；
- bar 判据：长度 ≥ min_len_px、宽度 ≤ max_width_px、实积率 area/bbox ≥ min_solidity
  （线框圆环实积率低，借此与筋条区分，环留给几何 loop）；
- 中心线：像素集 PCA 主轴（幂迭代，纯标准库），端点=主轴投影极值；
  宽度 = area / length（条形稳健估计，优于逐点最大垂距）；
- 本模块只输出像素系结果，mm 换算由 plan 经 t4 scale_solver.px_to_mm 完成。
"""

from __future__ import annotations

import math

from . import morph as _morph
from .components import label


def _pca_axis(pxs):
    """幂迭代求像素集主轴单位向量。返回 ((ux, uy), (cx, cy))。"""
    n = len(pxs)
    cx = sum(p[0] for p in pxs) / n
    cy = sum(p[1] for p in pxs) / n
    sxx = sum((p[0] - cx) ** 2 for p in pxs) / n
    syy = sum((p[1] - cy) ** 2 for p in pxs) / n
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in pxs) / n
    ux, uy = (1.0, 0.0) if sxx >= syy else (0.0, 1.0)
    for _ in range(64):
        vx = sxx * ux + sxy * uy
        vy = sxy * ux + syy * uy
        norm = math.hypot(vx, vy)
        if norm < 1e-12:
            break
        vx, vy = vx / norm, vy / norm
        if abs(vx - ux) + abs(vy - uy) < 1e-9:
            ux, uy = vx, vy
            break
        ux, uy = vx, vy
    return (ux, uy), (cx, cy)


def extract_ribs(closed_binary, rib_se: int = 4, min_len_px: float = 20.0,
                 max_width_px: float = 8.0, min_solidity: float = 0.5):
    """返回 (ribs, rib_mask)：ribs 每项 {"pixels", "centerline_px", "width_px",
    "length_px", "confidence"}；rib_mask 为 rib 像素二值图（pipeline 用它从几何
    标记中剔除已作为 rib 的独立连通域，防 loop/rib 双重计数）。

    标注引线等细线也会落入候选——按 spec 分工，语义分类归 t4 Jev，
    本模块只保证几何准则（细、长、实）。
    """
    h, w = len(closed_binary), len(closed_binary[0])
    residue = _morph.tophat(closed_binary, rib_se)
    _, comps = label(residue, connectivity=8)
    ribs = []
    rib_mask = [[0] * w for _ in range(h)]
    for pxs in comps.values():
        area = len(pxs)
        xs = [p[0] for p in pxs]
        ys = [p[1] for p in pxs]
        bw = max(xs) - min(xs) + 1
        bh = max(ys) - min(ys) + 1
        solidity = area / (bw * bh)
        (ux, uy), (cx, cy) = _pca_axis(pxs)
        projs = [(p[0] - cx) * ux + (p[1] - cy) * uy for p in pxs]
        length = max(projs) - min(projs)
        if length < 1e-9:
            continue
        width = area / length
        if length < min_len_px or width > max_width_px or solidity < min_solidity:
            continue
        t0, t1 = min(projs), max(projs)
        c0 = [cx + ux * t0, cy + uy * t0]
        c1 = [cx + ux * t1, cy + uy * t1]
        aspect = length / max(width, 1e-9)
        ribs.append({
            "pixels": pxs,
            "centerline_px": [c0, c1],
            "width_px": width,
            "length_px": length,
            "confidence": round(aspect / (aspect + 3.0), 3),
        })
        for x, y in pxs:
            rib_mask[y][x] = 1
    ribs.sort(key=lambda r: -r["length_px"])
    return ribs, rib_mask
