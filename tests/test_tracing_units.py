"""t2 单元测试：image / geometry / morph / mask / components / stitch / ribs / plan。

纯标准库被测代码，双解释器可跑；本文件用 pytest 风格随仓库 harness 跑
（/opt/homebrew/opt/python@3.12/bin/python3.12 -m pytest）。
"""

import math

import pytest

from cadcraft.tracing import geometry as G
from cadcraft.tracing import morph as M
from cadcraft.tracing.components import (assign_roles, enclosed_background_components,
                                         extract_loops, label, marching_squares,
                                         stroke_wall_filter)
from cadcraft.tracing.image import GrayImage
from cadcraft.tracing.mask import mask_text_boxes, normalize_box
from cadcraft.tracing.plan import PlanBuilder, PlanError, v01_upgrade
from cadcraft.tracing.ribs import extract_ribs
from cadcraft.tracing.stitch import rects_touch, stitch_rects, union_outlines


def _scale():
    return {"px_per_mm": 2.0,
            "anchor": {"type": "dimension", "ocr_text": "120", "real_length_mm": 120.0,
                       "px_length": 240.0, "bbox_px": [100, 72, 151, 89],
                       "confidence": 0.93},
            "uncertain": False}


def _texts():
    return [{"text": "120", "bbox_px": [100, 72, 151, 89], "used_as_anchor": True},
            {"text": "20", "bbox_px": [300, 200, 351, 221], "used_as_anchor": False}]


# -- image ---------------------------------------------------------------

def test_pgm_roundtrip():
    img = GrayImage(17, 9, 255)
    img.fill_rect(2, 2, 8, 6, 0)
    img2 = GrayImage.from_pgm(img.to_pgm())
    assert img2.width == 17 and img2.height == 9
    assert img2.pixels == img.pixels


def test_fill_polygon_rect_count():
    img = GrayImage(30, 30, 255)
    img.fill_polygon([(5, 5), (15, 5), (15, 12), (5, 12)], 0)
    n = sum(row.count(0) for row in img.pixels)
    assert n == 10 * 7  # 像素中心判定：x5..14, y5..11


def test_background_corners():
    img = GrayImage(10, 10, 255)
    assert img.background() == 255


# -- geometry --------------------------------------------------------------

def test_signed_area_and_winding():
    ccw = [[0, 0], [10, 0], [10, 10], [0, 10]]  # 数学系 CCW
    assert G.signed_area(ccw) == pytest.approx(100.0)
    cw = G.ensure_winding(ccw, ccw=False, y_down=False)
    assert G.signed_area(cw) == pytest.approx(-100.0)


def test_point_in_polygon():
    sq = [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert G.point_in_polygon(5, 5, sq)
    assert not G.point_in_polygon(15, 5, sq)
    assert G.point_in_polygon(0, 5, sq)  # 边上算内部


def test_self_intersection():
    bowtie = [[0, 0], [10, 10], [10, 0], [0, 10]]
    assert not G.is_simple_polygon(bowtie)
    assert G.is_simple_polygon([[0, 0], [10, 0], [10, 10], [0, 10]])


def test_rdp_collapses_straight_line():
    pts = [[float(x), 0.0] for x in range(11)]
    assert G.rdp(pts, 0.5) == [[0.0, 0.0], [10.0, 0.0]]


def test_scanline_sets_iou():
    a = G.rasterize_polygon([[0, 0], [10, 0], [10, 10], [0, 10]], 20, 20)
    b = G.rasterize_polygon([[5, 5], [15, 5], [15, 15], [5, 15]], 20, 20)
    assert len(a) == 100
    assert G.sets_iou(a, a) == 1.0
    assert 0.1 < G.sets_iou(a, b) < 0.2  # 交 25 / 并 175


# -- morph -----------------------------------------------------------------

def test_close_bridges_gap():
    g = [[0] * 20 for _ in range(5)]
    for x in range(0, 8):
        g[2][x] = 1
    for x in range(11, 20):
        g[2][x] = 1
    closed = M.close(g, 2)  # 3px 缺口 ≤ 2r=4 → 桥接
    assert all(closed[2][x] == 1 for x in range(20))
    opened = M.close(g, 1)  # 3px 缺口 > 2r=2 → 不桥接
    assert opened[2][9] == 0 and opened[2][10] == 0


def test_tophat_keeps_thin():
    g = [[0] * 30 for _ in range(30)]
    for x in range(30):
        g[15][x] = 1  # 1px 横线
    for y in range(5, 25):
        for x in range(5, 25):
            g[y][x] = 1  # 20x20 实心块
    th = M.tophat(g, 4)
    assert th[15][0] == 1 and th[15][29] == 1  # 细线残留
    assert th[15][15] == 0  # 块内部被开运算吃掉后无残差


# -- mask ------------------------------------------------------------------

def test_normalize_box_clips_and_pads():
    assert normalize_box([100.4, 72.2, 150.6, 88.9], 400, 300, 3) == [97, 69, 154, 92]
    assert normalize_box([-50, -50, 5, 5], 400, 300, 3) == [0, 0, 9, 9]
    assert normalize_box([10, 10, 11, 11], 400, 300, 3) == [7, 7, 15, 15]
    assert normalize_box([], 400, 300, 3) is None


def test_mask_paints_background_only():
    img = GrayImage(40, 40, 255)
    img.fill_rect(5, 5, 20, 20, 0)
    out, painted = mask_text_boxes(img, [[5, 5, 20, 20]], pad=2)
    assert painted == [[3, 3, 23, 23]]
    assert out.get(10, 10) == 255  # 原几何被盖掉
    assert img.get(10, 10) == 0  # 原图不动（拷贝语义）


# -- components --------------------------------------------------------------

def test_label_two_components():
    g = [[0] * 20 for _ in range(10)]
    for y in range(2, 5):
        for x in range(2, 5):
            g[y][x] = 1
    for y in range(2, 5):
        for x in range(12, 15):
            g[y][x] = 1
    _, comps = label(g)
    assert len(comps) == 2


def test_enclosed_vs_stroke_wall():
    # 细线框（2px 壁）：内腔应被填掉
    g = [[0] * 40 for _ in range(30)]
    for x in range(5, 26):
        g[5][x] = g[6][x] = g[23][x] = g[24][x] = 1
    for y in range(5, 25):
        g[y][5] = g[y][6] = g[y][24] = g[y][25] = 1
    ext, enc = enclosed_background_components(g)
    assert len(enc) == 1
    filled, info = stroke_wall_filter(g, enc, ext, max_wall_px=3)
    assert list(info.values())[0]["filled"] is True
    assert list(info.values())[0]["wall"] == 2
    # 厚面板真孔（壁 30px）：保留
    g2 = [[0] * 120 for _ in range(100)]
    for y in range(10, 90):
        for x in range(10, 110):
            g2[y][x] = 1
    for y in range(40, 60):
        for x in range(50, 70):
            g2[y][x] = 0
    ext2, enc2 = enclosed_background_components(g2)
    assert len(enc2) == 1
    _, info2 = stroke_wall_filter(g2, enc2, ext2, max_wall_px=3)
    assert list(info2.values())[0]["filled"] is False
    assert list(info2.values())[0]["wall"] >= 30


def test_marching_squares_closed_ring():
    g = [[0] * 20 for _ in range(20)]
    for y in range(5, 15):
        for x in range(5, 15):
            g[y][x] = 1
    loops, _ = extract_loops(g)
    assert len(loops) == 1
    assert loops[0]["kind"] == "outer-candidate"
    # MS 半像素边界 + RDP 转角切角（eps 量级）：小尺寸相对误差大，大尺寸可忽略
    assert abs(loops[0]["area_px"] - 100.0) < 12.0


def test_assign_roles_singleton_and_multi():
    loops, _ = extract_loops([[0] * 8 for _ in range(8)])
    assert assign_roles(loops) == []
    g = [[0] * 40 for _ in range(20)]
    for y in range(2, 18):
        for x in range(2, 18):
            g[y][x] = 1
    for y in range(2, 18):
        for x in range(25, 35):
            g[y][x] = 1
    loops, _ = extract_loops(g)
    assign_roles(loops)
    roles = sorted(l["role"] for l in loops)
    assert roles == ["detail", "outer"]
    assert loops[0]["id"] in ("outer_0", "detail_0")


# -- stitch ------------------------------------------------------------------

def test_stitch_rects_gap_closure():
    rects = [[0, 0, 10, 10], [11, 0, 20, 10], [50, 50, 60, 60]]
    merged = stitch_rects(rects, gap_tol=2.0)
    assert [0.0, 0.0, 20.0, 10.0] in merged
    assert [50.0, 50.0, 60.0, 60.0] in merged
    assert len(merged) == 2
    assert rects_touch([0, 0, 10, 10], [10, 0, 20, 10], 0.0)


def test_union_outlines_exact():
    a = [[10, 10], [60, 10], [60, 60], [10, 60]]
    b = [[40, 40], [90, 40], [90, 90], [40, 90]]
    loops = union_outlines([a, b], 120, 120)
    assert len(loops) == 1
    ua = G.rasterize_polygon(a, 120, 120) | G.rasterize_polygon(b, 120, 120)
    back = G.rasterize_polygon(loops[0]["points_px"], 120, 120)
    # MS 半像素边界量化：IoU 0.90 + 面积 5% 双控（合并正确性不断言亚像素）
    assert G.sets_iou(ua, back) >= 0.90
    assert abs(loops[0]["area_px"] - len(ua)) / len(ua) <= 0.05


# -- ribs --------------------------------------------------------------------

def test_extract_ribs_bar_vs_ring():
    g = [[0] * 120 for _ in range(60)]
    for x in range(10, 70):  # 60x4 筋条
        for y in range(20, 24):
            g[y][x] = 1
    for x in range(80, 110):  # 30x20 线框环（壁 2px）
        g[10][x] = g[11][x] = g[28][x] = g[29][x] = 1
    for y in range(10, 30):
        g[y][80] = g[y][81] = g[y][108] = g[y][109] = 1
    ribs, mask = extract_ribs(g)
    assert len(ribs) == 1  # 环实积率低，被排除
    assert ribs[0]["length_px"] == pytest.approx(59.0, abs=1.5)
    assert ribs[0]["width_px"] == pytest.approx(4.0, abs=0.6)
    assert sum(sum(row) for row in mask) == 60 * 4


# -- plan --------------------------------------------------------------------

def _builder():
    b = PlanBuilder(_scale(), 400, 300, source="u.png")
    b.set_texts_masked(_texts())
    return b


def test_builder_accepts_implicit_ring_and_enforces_winding():
    b = _builder()
    # CAD 系(y上)顺时针 outer → 自动纠正为 CCW + 警告
    cw_outer = [[0, 0], [0, 80], [120, 80], [120, 40], [40, 40], [40, 0]]
    assert G.signed_area(cw_outer) < 0
    b.add_loop([[x * 2, 300 - y * 2] for x, y in cw_outer], role="outer")
    assert b.warnings and "环绕方向" in b.warnings[0]
    plan = b.build()
    assert G.signed_area(plan["loops"][0]["points"]) > 0


def test_builder_rejects_self_intersection_and_d4():
    b = _builder()
    with pytest.raises(PlanError):
        b.add_loop([[0, 300], [50, 250], [50, 300], [0, 250]], role="outer")
    b2 = _builder()
    b2.add_loop([[0, 300], [200, 300], [200, 100], [0, 100]], role="outer")
    b2.add_loop([[10, 290], [130, 290], [130, 110], [10, 110]], role="hole")
    with pytest.raises(PlanError):  # hole 占 outer 54% → D4 在 build 时触发
        b2.build()


def test_builder_notch_role_ok_and_anchor_check():
    b = _builder()
    b.add_loop([[0, 300], [200, 300], [200, 100], [0, 100]], role="outer")
    b.add_loop([[200, 220], [240, 220], [240, 180], [200, 180]], role="notch")
    plan = b.build()
    assert [l["role"] for l in plan["loops"]] == ["outer", "notch"]
    b3 = PlanBuilder(_scale(), 400, 300)
    b3.set_texts_masked([])  # dimension anchor 却无 mask 记录 → 拒收
    b3.add_loop([[0, 300], [200, 300], [200, 100], [0, 100]], role="outer")
    with pytest.raises(PlanError):
        b3.build()


def test_builder_rib_validation():
    b = _builder()
    b.add_loop([[0, 300], [200, 300], [200, 100], [0, 100]], role="outer")
    with pytest.raises(PlanError):
        b.add_rib([[10, 10]], 2.0)
    with pytest.raises(PlanError):
        b.add_rib([[10, 10], [20, 20]], 0.0)
    b.add_rib([[80, 140], [160, 140]], 5.0, confidence=0.8)
    assert b.build()["ribs"][0]["width_mm"] == pytest.approx(2.5)


def test_v01_upgrade_is_manual_uncertain():
    plan = v01_upgrade({"polygon": [[0, 0], [50, 0], [50, 30], [0, 30]],
                        "scale_px_per_mm": 3.78}, 400, 300, source="old.png")
    assert plan["version"] == "0.2" and len(plan["loops"]) == 1
    assert plan["scale"]["anchor"]["type"] == "manual"
    assert plan["scale"]["uncertain"] is True
    assert plan["ribs"] == [] and plan["texts_masked"] == []
