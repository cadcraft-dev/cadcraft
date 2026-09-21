"""连通域 + 轮廓提取（spec §4.2 / R2 修复）：RETR_CCOMP 语义。

管线（全在像素系，y 向下）：
  label_foreground(8连通) → enclosed_background(4连通背底，不接边即包围区)
  → stroke_interior_filter（壁厚 BFS：薄壁线框内腔填掉，真孔保留）
  → marching_squares 全图等值线 → chain_loops 串环
  → assign_roles（最大顶层环=outer；被包围=hole；其余=detail）。

鞍点（case 5/10）取“前景分离”一致消歧； diagonal 单点接触的两环可能在顶点处
相切——assign_roles 用严格内点采样 + point_in_polygon，不依赖顶点相接关系。
"""

from __future__ import annotations

from collections import deque

from .geometry import point_in_polygon, signed_area


# -- 连通域标记 ------------------------------------------------------------

class _UnionFind:
    def __init__(self):
        self.p = {}

    def find(self, a):
        p = self.p.setdefault(a, a)
        while self.p[p] != p:
            self.p[p] = self.p[self.p[p]]
            p = self.p[p]
        return p

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def label(binary, connectivity: int = 8):
    """两遍扫描连通域。返回 (labels, comps)：labels[y][x]≥0，comps[label]为像素表。"""
    h, w = len(binary), len(binary[0])
    labels = [[-1] * w for _ in range(h)]
    uf = _UnionFind()
    nxt = 0
    if connectivity == 8:
        neigh = [(-1, -1), (-1, 0), (-1, 1), (0, -1)]
    else:
        neigh = [(-1, 0), (0, -1)]
    for y in range(h):
        for x in range(w):
            if not binary[y][x]:
                continue
            adj = [labels[y + dy][x + dx] for dy, dx in neigh
                   if 0 <= x + dx < w and 0 <= y + dy < h and labels[y + dy][x + dx] >= 0]
            if not adj:
                labels[y][x] = nxt
                uf.p[nxt] = nxt
                nxt += 1
            else:
                m = min(adj)
                labels[y][x] = m
                for a in adj:
                    uf.union(m, a)
    comps = {}
    for y in range(h):
        for x in range(w):
            if labels[y][x] >= 0:
                r = uf.find(labels[y][x])
                labels[y][x] = r
                comps.setdefault(r, []).append((x, y))
    # 重编号 0..k-1（稳定可复现）
    remap = {old: new for new, old in enumerate(sorted(comps))}
    labels = [[remap[v] if v >= 0 else -1 for v in row] for row in labels]
    comps = {remap[old]: px for old, px in comps.items()}
    return labels, comps


def enclosed_background_components(fg_binary):
    """背景 4 连通标记；不接触图边的背景连通域 = 被包围区（hole 候选/线框内腔）。

    返回 (exterior_mask, enclosed)：exterior_mask 为接边背景像素集合，
    enclosed 为 {label: 像素表}。
    """
    h, w = len(fg_binary), len(fg_binary[0])
    bg = [[0 if fg_binary[y][x] else 1 for x in range(w)] for y in range(h)]
    _, comps = label(bg, connectivity=4)
    exterior = set()
    enclosed = {}
    for lab, pxs in comps.items():
        touches = any(x == 0 or y == 0 or x == w - 1 or y == h - 1 for x, y in pxs)
        if touches:
            exterior.update(pxs)
        else:
            enclosed[lab] = pxs
    return exterior, enclosed


def stroke_wall_filter(fg_binary, enclosed, exterior, max_wall_px: int = 3):
    """线框内腔 vs 真孔：从包围区像素出发穿过前景做 BFS，到外背底的最短步数−1
    即包围壁厚。壁厚 ≤ max_wall_px 视为细线框内腔 → 填掉；否则真孔保留。

    返回 (filled_binary, info)：info[hole_label] = {"pixels", "wall", "filled"}。
    歧义记录在案：贴边真孔（薄韧带）可能被填——调用方用 min_hole_area 兜底，
    见 pipeline.extract_loops。
    """
    h, w = len(fg_binary), len(fg_binary[0])
    filled = [row[:] for row in fg_binary]
    exterior_set = set(exterior)
    info = {}
    for lab, pxs in enclosed.items():
        hole = set(pxs)
        dist = {p: 0 for p in pxs}
        q = deque(pxs)
        wall = None
        while q:
            x, y = q.popleft()
            d = dist[(x, y)]
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not (0 <= nx < w and 0 <= ny < h) or (nx, ny) in dist:
                    continue
                if (nx, ny) in exterior_set:
                    wall = d + 1 - 1  # 穿过的前景格数
                    q.clear()
                    break
                if filled[ny][nx] == 1:
                    dist[(nx, ny)] = d + 1
                    q.append((nx, ny))
        if wall is None:
            wall = 10 ** 9  # 无外背底可达（整图被前景包住的极端情形）→ 按真孔保留
        do_fill = wall <= max_wall_px
        if do_fill:
            for x, y in pxs:
                filled[y][x] = 1
        info[lab] = {"pixels": pxs, "wall": wall, "filled": do_fill}
    return filled, info


# -- Marching squares ------------------------------------------------------

# doubled 坐标：T=(2x+1,2y) R=(2x+2,2y+1) B=(2x+1,2y+2) L=(2x,2y+1)；
# casebits: a(TL)=8 b(TR)=4 c(BR)=2 d(BL)=1。鞍点 5/10 取前景分离。
_MS_SEGS = {
    1: [("L", "B")], 2: [("B", "R")], 3: [("L", "R")],
    4: [("T", "R")], 5: [("T", "R"), ("L", "B")], 6: [("T", "B")],
    7: [("T", "L")], 8: [("T", "L")], 9: [("T", "B")],
    10: [("T", "L"), ("B", "R")], 11: [("T", "R")], 12: [("L", "R")],
    13: [("B", "R")], 14: [("L", "B")],
}

# 每段的“背景侧采样点”（单元内相对 doubled 偏移）：用于嵌套归属判定的严格内点。
# 背景侧 = 非前景角一侧的单元中心方向。
_MS_BG_SAMPLE = {
    1: (0.5, -0.25), 2: (-0.5, -0.25), 3: (0.0, -0.5),
    4: (-0.25, 0.5), 5: None, 6: (-0.5, 0.0),
    7: (0.25, -0.5), 8: (-0.25, -0.5), 9: (0.5, 0.0),
    10: None, 11: (0.25, 0.5), 12: (0.0, 0.5),
    13: (0.5, 0.25), 14: (-0.5, 0.25),
}


def _edge_vertex(kind, x, y):
    if kind == "T":
        return (2 * x + 1, 2 * y)
    if kind == "R":
        return (2 * x + 2, 2 * y + 1)
    if kind == "B":
        return (2 * x + 1, 2 * y + 2)
    return (2 * x, 2 * y + 1)  # L


def marching_squares(binary):
    """返回段表 [(v0, v1, sample)]：v 为 doubled 全局坐标，sample 为背景侧采样点
    （鞍点段 sample=None，串环时借用同环其他段）。自动加 1px 背景边框。"""
    h, w = len(binary), len(binary[0])
    segs = []
    for y in range(-1, h):
        for x in range(-1, w):
            def at(ix, iy):
                if 0 <= ix < w and 0 <= iy < h:
                    return binary[iy][ix]
                return 0

            a, b, c, d = at(x, y), at(x + 1, y), at(x + 1, y + 1), at(x, y + 1)
            case = a * 8 + b * 4 + c * 2 + d
            if case in (0, 15):
                continue
            for e0, e1 in _MS_SEGS[case]:
                v0, v1 = _edge_vertex(e0, x, y), _edge_vertex(e1, x, y)
                off = _MS_BG_SAMPLE[case]
                if off is None:
                    sample = None
                else:
                    mx = (v0[0] + v1[0]) / 2.0 + off[0] * 2
                    my = (v0[1] + v1[1]) / 2.0 + off[1] * 2
                    sample = (mx / 2.0, my / 2.0)
                segs.append((v0, v1, sample))
    return segs


def chain_loops(segs):
    """无向段串环。返回 [{"points": [(x,y)...doubled全局], "sample": (x,y) 全局浮点}]。"""
    adj = {}
    for i, (v0, v1, _) in enumerate(segs):
        adj.setdefault(v0, []).append(i)
        adj.setdefault(v1, []).append(i)
    used = [False] * len(segs)
    loops = []
    for i, (v0, v1, s) in enumerate(segs):
        if used[i]:
            continue
        used[i] = True
        chain = [v0, v1]
        samples = [s] if s else []
        prev, cur = v0, v1
        while cur != v0:
            nxt = None
            for j in adj.get(cur, []):
                if not used[j]:
                    nxt = j
                    break
            if nxt is None:
                break  # 退化（贴边/奇异接触）→ 就地闭环
            used[nxt] = True
            a, b, s2 = segs[nxt]
            cur = b if a == cur else a
            chain.append(cur)
            if s2:
                samples.append(s2)
        if chain[0] == chain[-1]:
            chain.pop()
        loops.append({"points": chain, "sample": samples[0] if samples else None})
    return loops


def _dedup(points):
    out = []
    for p in points:
        if not out or out[-1] != p:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def extract_loops(fg_binary, rdp_eps: float = 0.6, min_loop_area_px: float = 25.0,
                  min_hole_area_px: float = 16.0):
    """marching squares → 化简 → 嵌套归属。返回 loop 列表：

    {"points_px": [[x,y]...]（像素系浮点，去重闭环）, "area_px": float,
     "kind": "outer-candidate" | "hole-candidate", "sample": (x,y)}。
    角色（outer/hole/detail）由 assign_roles 在全局比较后确定。
    """
    from .geometry import rdp

    segs = marching_squares(fg_binary)
    loops = []
    for lp in chain_loops(segs):
        pts = [(v[0] / 2.0, v[1] / 2.0) for v in _dedup(lp["points"])]
        if len(pts) < 3:
            continue
        area = abs(signed_area(pts))
        if area < min_loop_area_px:
            continue
        simp = rdp(pts + [pts[0]], rdp_eps)
        if simp[0] == simp[-1]:
            simp.pop()
        simp = _dedup(simp)
        if len(simp) < 3 or not simp:
            continue
        area2 = abs(signed_area(simp))
        if area2 < min_loop_area_px:
            continue
        sample = lp["sample"]
        loops.append({"points_px": [[float(x), float(y)] for x, y in simp],
                      "area_px": area2, "sample": sample})
    # 嵌套归属：sample 点严格在某环内 → hole-candidate（鞍点 sample 缺失时用环心代替）
    for lp in loops:
        s = lp["sample"]
        if s is None:
            xs = [p[0] for p in lp["points_px"]]
            ys = [p[1] for p in lp["points_px"]]
            s = (sum(xs) / len(xs), sum(ys) / len(ys))
            lp["sample"] = s
        containers = [other for other in loops if other is not lp
                      and point_in_polygon(s[0], s[1], other["points_px"])]
        lp["kind"] = "hole-candidate" if containers else "outer-candidate"
        lp["_containers"] = len(containers)
    # hole 太小（噪点腔）→ 降级忽略，由调用方填掉
    tiny_holes = [lp for lp in loops
                  if lp["kind"] == "hole-candidate" and lp["area_px"] < min_hole_area_px]
    for lp in tiny_holes:
        loops.remove(lp)
    return loops, {"tiny_holes_dropped": len(tiny_holes)}


def assign_roles(loops):
    """全局角色分配：最大顶层环=outer；其余顶层=detail；被包围=hole（面积降序编号）。

    返回 {(role, idx)} 写入每项的 "role"/"id"。恰好 1 个 outer（空输入返回空）。
    """
    if not loops:
        return loops
    tops = sorted([lp for lp in loops if lp["kind"] == "outer-candidate"],
                  key=lambda l: -l["area_px"])
    holes = sorted([lp for lp in loops if lp["kind"] == "hole-candidate"],
                   key=lambda l: -l["area_px"])
    for i, lp in enumerate(tops):
        lp["role"] = "outer" if i == 0 else "detail"
        lp["id"] = f"outer_0" if i == 0 else f"detail_{i - 1}"
    for i, lp in enumerate(holes):
        lp["role"] = "hole"
        lp["id"] = f"hole_{i}"
    return loops
