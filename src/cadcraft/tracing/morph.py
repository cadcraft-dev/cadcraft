"""二值形态学（纯标准库）：膨胀/腐蚀/开/闭/tophat，方形结构元，可分两次一维通过。

用途（t2）：
- ``close``：缝合虚线断线/扫描缺口（多边形碎片缝合，无偏：膨胀后再腐蚀回来）；
- ``tophat``：残差提取细结构（ribs 加强筋 / 细线候选）；
- ``open``：去散点噪（谨慎使用，会吃掉 rib，小 radius 专用）。
"""

from __future__ import annotations


def _pass_rows(g, r: int, fn):
    h, w = len(g), len(g[0])
    out = [[0] * w for _ in range(h)]
    for y in range(h):
        row, grow = out[y], g[y]
        for x in range(w):
            x0 = max(0, x - r)
            x1 = min(w - 1, x + r)
            row[x] = fn(grow[x0 : x1 + 1])
    return out


def _pass_cols(g, r: int, fn):
    h, w = len(g), len(g[0])
    out = [[0] * w for _ in range(h)]
    for x in range(w):
        for y in range(h):
            y0 = max(0, y - r)
            y1 = min(h - 1, y + r)
            out[y][x] = fn(g[yy][x] for yy in range(y0, y1 + 1))
    return out


def dilate(g, r: int):
    """方形结构元膨胀（半径 r，边长 2r+1）；r<=0 返回拷贝。"""
    if r <= 0:
        return [row[:] for row in g]
    any_fn = lambda vals: 1 if any(vals) else 0
    return _pass_cols(_pass_rows(g, r, any_fn), r, any_fn)


def erode(g, r: int):
    """方形结构元腐蚀；r<=0 返回拷贝。"""
    if r <= 0:
        return [row[:] for row in g]
    all_fn = lambda vals: 1 if all(vals) else 0
    return _pass_cols(_pass_rows(g, r, all_fn), r, all_fn)


def open_(g, r: int):
    """开运算：先腐蚀后膨胀，去孤立噪点（r 一般取 1）。"""
    return dilate(erode(g, r), r)


def close(g, r: int):
    """闭运算：先膨胀后腐蚀，桥接 ≤2r 的断线缺口，形状无偏（尺寸还原）。"""
    return erode(dilate(g, r), r)


def tophat(g, r: int):
    """顶帽残差 g − open(g)：留下比结构元细的结构（rib/细线候选）。"""
    o = open_(g, r)
    return [[1 if g[y][x] and not o[y][x] else 0 for x in range(len(g[0]))]
            for y in range(len(g))]


def subtract(a, b):
    return [[1 if a[y][x] and not b[y][x] else 0 for x in range(len(a[0]))]
            for y in range(len(a))]


def count(g) -> int:
    return sum(sum(row) for row in g)
