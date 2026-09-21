"""t5 bench 绘制/GT 构造库（合成图 → 真实管线 → 真实 verifier）。

约定（诚实优先）：
- 全部 case 经 ``trace_drawing`` 端到端实测，不手写 plan 冒充（负对照除外，
  负对照即为故意的手写单矩形）。
- GT 几何由绘图真值按 ``X=x/S, Y=(H-y)/S`` 程序换算，环绕方向程序归一
  （outer-CCW/hole-CW），与检测输出无关。
- ``key_dimensions`` 索引：方孔边与起点无关（正方形）；外轮廓长边索引经
  “同一物理边”对齐（见 docs/tracing-benchmark.md 已知缺口 N2），
  对齐后 GT 多边形本身不变（仅顶点起点约定）。
- L1 无 key_dimensions（shape-only，verifier 按 L1 门限走）。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")

from cadcraft.tracing.geometry import signed_area  # noqa: E402
from cadcraft.tracing.image import GrayImage  # noqa: E402
from cadcraft.tracing.pipeline import trace_drawing  # noqa: E402
from cadcraft.verifier.verifier import verify_plan  # noqa: E402


def cad_points(px_pts, s: float, h: int) -> list:
    """图像系折线 → CAD 系 mm（spec §4.2 D1）。"""
    return [[x / s, (h - y) / s] for x, y in px_pts]


def ccw(points):
    pts = [list(p) for p in points]
    return pts if signed_area(pts) > 0 else list(reversed(pts))


def cw(points):
    pts = [list(p) for p in points]
    return pts if signed_area(pts) < 0 else list(reversed(pts))


def rect_cad(x0, y0, x1, y1, s: float, h: int):
    """像素矩形（x1/y1 开区间，fill_rect 语义）→ CAD 矩形（CCW）。"""
    pts = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
    return ccw(cad_points(pts, s, h))


def gt_loop(lid, role, points):
    return {"id": lid, "role": role, "points": points}


def gt_key(kid, loop_id, edge, length_mm):
    return {"id": kid, "loop_id": loop_id, "edge": list(edge), "length_mm": length_mm}


# ---------------------------------------------------------------- L1 ---

def build_l1(name, s, canvas, rect, dim_text=None):
    """单矩形。dim_text 为 None 时无 OCR（manual/uncertain，见缺口 N1）；
    否则带一条尺寸标注（S 可解，测纯检测质量）。"""
    w, h = canvas
    x0, y0, x1, y1 = rect
    img = GrayImage(w, h, 255)
    img.fill_rect(x0, y0, x1, y1, 0)
    ocr = []
    if dim_text is not None:
        text, bbox, px_len = dim_text
        bx0, by0, bx1, by1 = bbox
        img.fill_rect(bx0, by0, bx1, by1, 0)
        ocr = [{"text": text, "bbox_px": [bx0, by0, bx1, by1],
                "px_length": float(px_len), "confidence": 0.93}]
    gt = {"loops": [gt_loop("outer_0", "outer",
                            rect_cad(x0, y0, x1, y1, s, h))],
          "ribs": []}
    return {"name": name, "level": "L1", "image": img, "ocr": ocr,
            "gt": gt, "source": f"{name}.png",
            "expect": "PASS"}


def l1_cases():
    s = 4.0
    return [
        # 100x40mm，底边标注 100（400px @S=4）
        build_l1("L1a", s, (500, 340), (60, 60, 460, 220),
                 ("100", [180, 260, 300, 277], 400.0)),
        build_l1("L1b", 3.0, (440, 360), (30, 30, 270, 210),
                 ("80", [120, 250, 210, 267], 240.0)),
        build_l1("L1c", s, (360, 300), (100, 100, 260, 200),
                 ("40", [130, 230, 200, 247], 160.0)),
    ]


def l1_manual_case():
    """N1 缺口演示：同一 L1a 图、无 OCR → manual scale 导致 mm-IoU 丢失。
    预期 FAIL（检测形状正确，错在 fallback S=3.78）。"""
    case = build_l1("L1a-manual", 4.0, (500, 340), (60, 60, 460, 220), None)
    case["expect"] = "FAIL(N1)"
    return case


# ---------------------------------------------------------------- L2 ---

L2A_S, L2A_W, L2A_H = 4.0, 800, 600
L2A_L_PX = [(80, 440), (80, 160), (560, 160), (560, 240), (240, 240), (240, 440)]
L2A_HOLE = (320, 170, 380, 230)     # 60x60px = 15mm 方孔（量化误差<2%）
L2A_RIB = (400, 360, 522, 366)      # 背景孤立筋条 122x6px（宽≤8px 才能进 rib 滤波）
L2A_OCR = [
    {"text": "120", "bbox_px": [200, 40, 360, 74],
     "px_length": 480.0, "confidence": 0.93},
    {"text": "20", "bbox_px": [600, 400, 702, 442], "confidence": 0.9},
]
# 外轮廓顶边（120mm）在 GT 点列中的索引：按“同一物理边”与当前 tracer
# 的输出循环顺序对齐（缺口 N2）。GT 多边形本身不变，仅起点/方向约定；
# 若 tracer 改动导致点序变化，此处会显式失配（bench FAIL 而非静默通过）。
L2A_TOP_EDGE = [4, 5]


def _l2a_outer_gt():
    pts = cad_points(L2A_L_PX, L2A_S, L2A_H)
    pts = ccw(pts)          # 规范形：[(20,40),(20,110),(140,110),(140,90),(60,90),(60,40)]
    pts = list(reversed(pts))
    start = min(range(len(pts)), key=lambda i: (pts[i][0] + pts[i][1]))
    return pts[start:] + pts[:start]


def build_l2a():
    img = GrayImage(L2A_W, L2A_H, 255)
    img.fill_polygon(L2A_L_PX, 0)
    img.fill_rect(*L2A_HOLE, 255)
    img.fill_rect(*L2A_RIB, 0)
    for t in L2A_OCR:
        x0, y0, x1, y1 = t["bbox_px"]
        img.fill_rect(x0, y0, x1, y1, 0)
    gt = {
        "loops": [
            gt_loop("outer_0", "outer", _l2a_outer_gt()),
            gt_loop("hole_0", "hole", cw(rect_cad(*L2A_HOLE, L2A_S, L2A_H))),
        ],
        "ribs": [{"id": "rib_0",
                  "centerline": [[400 / L2A_S, (L2A_H - 363) / L2A_S],
                                 [521 / L2A_S, (L2A_H - 363) / L2A_S]],
                  "width_mm": 6 / L2A_S}],
        "key_dimensions": [
            gt_key("k_outer_top", "outer_0", L2A_TOP_EDGE, 480 / L2A_S),
            gt_key("k_hole", "hole_0", [0, 1], 60 / L2A_S),
        ],
    }
    return {"name": "L2a", "level": "L2", "image": img, "ocr": L2A_OCR,
            "gt": gt, "source": "level2_bracket.png", "expect": "PASS"}


L2B_S, L2B_W, L2B_H = 4.0, 480, 360
L2B_PLATE = (40, 60, 440, 300)
L2B_H1 = (100, 120, 148, 168)       # 48px = 12mm
L2B_H2 = (300, 180, 332, 212)       # 32px = 8mm
L2B_RIB = (180, 308, 300, 314)      # 背景孤立筋条 120x6px（板下方）
L2B_OCR = [
    {"text": "100", "bbox_px": [330, 310, 430, 327],
     "px_length": 400.0, "confidence": 0.93},
    {"text": "12", "bbox_px": [40, 310, 90, 327], "confidence": 0.9},
]


def build_l2b():
    img = GrayImage(L2B_W, L2B_H, 255)
    img.fill_rect(*L2B_PLATE, 0)
    img.fill_rect(*L2B_H1, 255)
    img.fill_rect(*L2B_H2, 255)
    img.fill_rect(*L2B_RIB, 0)
    for t in L2B_OCR:
        x0, y0, x1, y1 = t["bbox_px"]
        img.fill_rect(x0, y0, x1, y1, 0)
    gt = {
        "loops": [
            gt_loop("outer_0", "outer",
                    ccw(rect_cad(*L2B_PLATE, L2B_S, L2B_H))),
            gt_loop("hole_0", "hole", cw(rect_cad(*L2B_H1, L2B_S, L2B_H))),
            gt_loop("hole_1", "hole", cw(rect_cad(*L2B_H2, L2B_S, L2B_H))),
        ],
        "ribs": [{"id": "rib_0",
                  "centerline": [[180 / L2B_S, (L2B_H - 311) / L2B_S],
                                 [299 / L2B_S, (L2B_H - 311) / L2B_S]],
                  "width_mm": 6 / L2B_S}],
        "key_dimensions": [
            gt_key("k_h1", "hole_0", [0, 1], 48 / L2B_S),
            gt_key("k_h2", "hole_1", [0, 1], 32 / L2B_S),
        ],
    }
    return {"name": "L2b", "level": "L2", "image": img, "ocr": L2B_OCR,
            "gt": gt, "source": "level2_plate.png", "expect": "PASS"}


# ---------------------------------------------------------------- L3 ---

L3_S, L3_W, L3_H = 4.0, 640, 420
L3_PLATE = (40, 60, 520, 340)
L3_HOLES = [(100, 120, 148, 168),   # 12mm
            (220, 140, 260, 180),   # 10mm
            (360, 200, 392, 232)]   # 8mm
L3_RIBS = [(60, 360, 180, 366),     # 横筋（板下方背景）
           (560, 100, 566, 220)]    # 竖筋（板右侧背景）
L3_OCR = [
    {"text": "120", "bbox_px": [180, 360, 300, 377],
     "px_length": 480.0, "confidence": 0.94},
    {"text": "12", "bbox_px": [400, 360, 450, 377], "confidence": 0.9},
]


def build_l3():
    img = GrayImage(L3_W, L3_H, 255)
    img.fill_rect(*L3_PLATE, 0)
    for hb in L3_HOLES:
        img.fill_rect(*hb, 255)
    for rb in L3_RIBS:
        img.fill_rect(*rb, 0)
    for t in L3_OCR:
        x0, y0, x1, y1 = t["bbox_px"]
        img.fill_rect(x0, y0, x1, y1, 0)
    holes = [gt_loop(f"hole_{i}", "hole", cw(rect_cad(*hb, L3_S, L3_H)))
             for i, hb in enumerate(L3_HOLES)]
    (rx0, ry0, rx1, ry1), (vx0, vy0, vx1, vy1) = L3_RIBS
    ribs = [
        {"id": "rib_0",
         "centerline": [[rx0 / L3_S, (L3_H - (ry0 + ry1) / 2) / L3_S],
                        [rx1 / L3_S, (L3_H - (ry0 + ry1) / 2) / L3_S]],
         "width_mm": (ry1 - ry0) / L3_S},
        {"id": "rib_1",
         "centerline": [[(vx0 + vx1) / 2 / L3_S, (L3_H - vy0) / L3_S],
                        [(vx0 + vx1) / 2 / L3_S, (L3_H - vy1) / L3_S]],
         "width_mm": (vx1 - vx0) / L3_S},
    ]
    keys = [gt_key(f"k_h{i}", f"hole_{i}", [0, 1], (hb[2] - hb[0]) / L3_S)
            for i, hb in enumerate(L3_HOLES)]
    gt = {"loops": [gt_loop("outer_0", "outer",
                            ccw(rect_cad(*L3_PLATE, L3_S, L3_H)))] + holes,
          "ribs": ribs, "key_dimensions": keys}
    return {"name": "L3a", "level": "L3", "image": img, "ocr": L3_OCR,
            "gt": gt, "source": "level3_assembly.png", "expect": "PASS(ref)"}


# ------------------------------------------------------- 负对照/v0.1 ---

def build_spoof_l2a():
    """故意用单矩形冒充 L2a：bbox 与真值同一外包，anchor 合法，
    只有 §8.3 规则应当开火。"""
    case = build_l2a()
    plan, _ = trace_drawing(case["image"], ocr_items=case["ocr"],
                            source=case["source"])
    xs = [20.0, 140.0]
    ys = [40.0, 110.0]
    plan["loops"] = [{"id": "outer_0", "role": "outer",
                      "points": [[xs[0], ys[0]], [xs[1], ys[0]],
                                 [xs[1], ys[1]], [xs[0], ys[1]]],
                      "closed": True, "area_mm2": 12000.0,
                      "confidence": 0.99, "source": "bbox-guess"}]
    plan["ribs"] = []
    return {"name": "L2-neg", "level": "L2", "plan": plan,
            "gt": case["gt"], "expect": "FAIL"}


def build_v01_baseline(case):
    """v0.1 最优手测基线：polygon 取真值矩形角点（mm），scale 取真值。"""
    w, h = case["image"].width, case["image"].height
    (x0, y0, x1, y1) = {"L1a": (60, 60, 460, 220),
                        "L1b": (30, 30, 270, 210),
                        "L1c": (100, 100, 260, 200)}[case["name"]]
    s = {"L1a": 4.0, "L1b": 3.0, "L1c": 4.0}[case["name"]]
    # CCW（CAD y-up：左下→右下→右上→左上），与 GT 同一起点约定无关，纯粹合 D3。
    return {"version": "0.1",
            "polygon": [[x0 / s, (h - y1) / s], [x1 / s, (h - y1) / s],
                        [x1 / s, (h - y0) / s], [x0 / s, (h - y0) / s]],
            "scale_px_per_mm": s}


def run_case(case):
    """实测单个 case：trace → verify。返回 (plan, report)。"""
    plan, _dbg = trace_drawing(case["image"], ocr_items=case["ocr"],
                               source=case["source"])
    report = verify_plan(plan, case["gt"], level="auto")
    return plan, report
