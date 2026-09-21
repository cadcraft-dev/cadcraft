"""t2 端到端测试：L2 bracket 合成夹具（outer L + 真孔 + rib + 2 处文字）。

- R3：同一张图 masked vs unmasked——掩膜消除粘连/伪环，环数回到 {outer, hole}；
- R2：真孔（厚壁包围）被检出为 hole；细线框内腔对照见 test_tracing_units；
- R4：scale 复用 t4 solve_scale，最长 OCR（120 > 20）当选 anchor，S=2.0；
- 产物用 verifier 侧 plan_io.validate_plan 交叉验证（t2→t3 契约）；
- L1 回归：单矩形 + 无 OCR → outer 单环 + manual/uncertain。
"""

import json
import os

import pytest

from cadcraft.tracing import pipeline as P
from cadcraft.tracing import scale_solver as SS
from cadcraft.tracing.geometry import (rasterize_polygon, scanline_fill, sets_iou,
                                       signed_area)
from cadcraft.tracing.image import GrayImage
from cadcraft.tracing.pipeline import trace_drawing

W, H = 400, 300
L_PX = [(40, 220), (40, 80), (280, 80), (280, 120), (120, 120), (120, 220)]
HOLE_PX = [160, 88, 181, 109]  # x160-180, y88-108（厚壁包围的真孔）
OCR = [
    {"text": "120", "bbox_px": [100, 72, 151, 89], "px_length": 240.0,
     "confidence": 0.93},
    {"text": "20", "bbox_px": [300, 200, 351, 221], "confidence": 0.9},
]


def make_bracket():
    img = GrayImage(W, H, 255)
    img.fill_polygon(L_PX, 0)
    img.fill_rect(*HOLE_PX, 255)
    img.fill_rect(200, 180, 261, 185, 0)  # rib 筋条 61x5
    img.fill_rect(100, 72, 151, 89, 0)  # 贴边文字（掩膜后在顶边留小咬口）
    img.fill_rect(300, 200, 351, 221, 0)  # 孤立文字块
    return img


def test_scale_reused_from_t4_not_reimplemented():
    assert P.solve_scale is SS.solve_scale
    assert P.__name__ == "cadcraft.tracing.pipeline"


def test_bracket_end_to_end():
    plan, dbg = trace_drawing(make_bracket(), ocr_items=OCR, source="bracket.png")
    # R4：最长 OCR 当选，S = 240px/120mm
    assert plan["scale"]["px_per_mm"] == pytest.approx(2.0)
    assert plan["scale"]["anchor"]["ocr_text"] == "120"
    assert plan["scale"]["uncertain"] is False
    assert {t["text"] for t in plan["texts_masked"]} == {"120", "20"}
    anchor_flags = [t for t in plan["texts_masked"] if t["used_as_anchor"]]
    assert len(anchor_flags) == 1 and anchor_flags[0]["text"] == "120"
    # R1/R2：outer + hole，无 detail 伪环；rib 独立一条（无双重计数）
    roles = sorted(l["role"] for l in plan["loops"])
    assert roles == ["hole", "outer"]
    assert len(plan["ribs"]) == 1
    assert plan["ribs"][0]["width_mm"] == pytest.approx(2.54, rel=0.2)
    # 像素级 IoU（spec D6 门限 0.90）
    gt_outer = rasterize_polygon(L_PX, W, H)
    det = {l["id"]: l for l in dbg["loops_px"]}
    det_outer = set()
    for x, y in scanline_fill(det["outer_0"]["points_px"]):
        if 0 <= x < W and 0 <= y < H:
            det_outer.add((x, y))
    assert sets_iou(gt_outer, det_outer) >= 0.90
    gt_hole = {(x, y) for x in range(160, 181) for y in range(88, 109)}
    det_hole = set()
    for x, y in scanline_fill(det["hole_0"]["points_px"]):
        det_hole.add((x, y))
    assert sets_iou(gt_hole, det_hole) >= 0.90
    # mm 级绝对尺寸（scale 实检，spec §7.3 口径 2%）
    xs = [p[0] for p in plan["loops"][0]["points"]]
    assert (max(xs) - min(xs)) == pytest.approx(120.0, rel=0.02)
    hole = [l for l in plan["loops"] if l["role"] == "hole"][0]
    assert hole["area_mm2"] == pytest.approx(110.25, rel=0.10)
    # rib 端点误差 ≤1mm（spec §7.2）
    cl = plan["ribs"][0]["centerline"]
    assert abs(cl[0][0] - 100.0) <= 1.0 and abs(cl[1][0] - 130.0) <= 1.0
    # D3：CAD 系 outer-CCW / hole-CW
    assert signed_area(plan["loops"][0]["points"]) > 0
    assert signed_area(hole["points"]) < 0


def test_mask_order_matters_r3():
    masked_plan, _ = trace_drawing(make_bracket(), ocr_items=OCR)
    raw_plan, _ = trace_drawing(make_bracket(), ocr_items=[])
    masked_roles = sorted(l["role"] for l in masked_plan["loops"])
    raw_roles = sorted(l["role"] for l in raw_plan["loops"])
    assert masked_roles == ["hole", "outer"]
    assert len(raw_roles) > len(masked_roles)  # 无掩膜：孤立文字块变成伪 detail 环
    assert "detail" in raw_roles


def test_l1_single_rect_no_regression():
    img = GrayImage(300, 200, 255)
    img.fill_rect(60, 60, 201, 161, 0)
    plan, _ = trace_drawing(img, ocr_items=[])
    assert [l["role"] for l in plan["loops"]] == ["outer"]
    assert plan["ribs"] == [] and plan["texts_masked"] == []
    assert plan["scale"]["anchor"]["type"] == "manual"
    assert plan["scale"]["uncertain"] is True


def test_gap_bridging_stitch():
    img = GrayImage(220, 160, 255)
    img.fill_rect(50, 50, 101, 101, 0)
    img.fill_rect(107, 50, 158, 101, 0)  # 6px 断口
    one, _ = trace_drawing(img, ocr_items=[], params={"gap_radius": 3})
    assert len(one["loops"]) == 1  # 闭运算桥接（无偏 stitch）
    two, _ = trace_drawing(img, ocr_items=[], params={"gap_radius": 0})
    assert len(two["loops"]) == 2  # 不桥接：两碎片


def test_output_passes_verifier_side_validation_and_schema():
    from cadcraft.plan_io import validate_plan

    plan, _ = trace_drawing(make_bracket(), ocr_items=OCR, source="bracket.png")
    assert validate_plan(plan)["version"] == "0.2"  # t2 产物过 t3 侧校验
    schema_path = os.path.join(os.path.dirname(__file__), "..", "docs",
                               "plan-v02.schema.json")
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    for key in schema["required"]:
        assert key in plan
    assert plan["version"] == schema["properties"]["version"]["const"]
    assert plan["units"] == schema["properties"]["units"]["const"]
    role_enum = schema["properties"]["loops"]["items"]["properties"]["role"]["enum"]
    assert all(l["role"] in role_enum for l in plan["loops"])
    assert all(l["closed"] is True for l in plan["loops"])
    assert sum(1 for l in plan["loops"] if l["role"] == "outer") == 1
    rib_schema = schema["properties"]["ribs"]["items"]
    assert all(len(r["centerline"]) >= rib_schema["properties"]["centerline"]["minItems"]
               for r in plan["ribs"])
