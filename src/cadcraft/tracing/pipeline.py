"""Tracing 主管线（t2）：OCR → text-mask → 几何检测 → stitch → 多 loop plan。

顺序铁律（spec §6）：OCR 先行，掩膜后检测。OCR 以可注入函数/列表形式进入，
无 OCR 引擎时传空列表（null_ocr），texts_masked 记 [] 并在 meta 注明。

scale 全权委托 t4 scale_solver.solve_scale（最长可信 OCR 反推 / manual 降级），
本模块只消费其返回的 scale + texts_masked，不做任何 scale 计算。

默认参数（合成验证与 L2 bracket 量级图标定，真实大图按需覆盖）：
  thresh=128, mask_pad=3, gap_radius=2, rdp_eps=0.6,
  min_loop_area_px=25, min_hole_area_px=16, max_wall_px=3,
  rib_se=4, rib_min_len_px=20, rib_max_width_px=8, rib_min_solidity=0.5
"""

from __future__ import annotations

from . import morph as _morph
from .components import (assign_roles, enclosed_background_components, extract_loops,
                         label, stroke_wall_filter)
from .mask import mask_text_boxes
from .plan import PlanBuilder
from .ribs import extract_ribs
from .scale_solver import solve_scale

DEFAULT_PARAMS = {
    "thresh": 128,
    "mask_pad": 3,
    "gap_radius": 2,
    "rdp_eps": 0.6,
    "min_loop_area_px": 25.0,
    "min_hole_area_px": 16.0,
    "max_wall_px": 3,
    "rib_se": 4,
    "rib_min_len_px": 20.0,
    "rib_max_width_px": 8.0,
    "rib_min_solidity": 0.5,
}


def null_ocr(image):
    """无 OCR 引擎时的空实现：返回 []（meta 会注明）。"""
    return []


def trace_drawing(image, ocr_items=None, ocr_fn=None, scale_override=None,
                  source: str = "", params: dict = None,
                  tracer: str = "t2-stitch", notes: str = ""):
    """全链路 tracing。返回 (plan, debug)。

    :param image: GrayImage。
    :param ocr_items: OCR 结果列表 [{text, bbox_px, px_length?, confidence?}]，
        与 ocr_fn 二选一（都给则合并，items 在前）。
    :param ocr_fn: callable(image) -> ocr_items（默认 null_ocr）。
    :param scale_override: 直接指定 {"scale", "texts_masked"}（solve_scale 形态，
        t4 精化后回注用；None 则内部 solve_scale）。texts_masked 缺失/为空时
        只有 manual+uncertain 才允许（§6 可审计性），否则报错。
    :param source: 图来源文件名（plan.image.source）。
    :param params: 覆盖 DEFAULT_PARAMS。
    """
    p = dict(DEFAULT_PARAMS)
    p.update(params or {})
    w, h = image.width, image.height

    # 1) OCR（注入式；顺序铁律第一步）
    items = list(ocr_items or [])
    if ocr_fn is not None:
        items = items + list(ocr_fn(image) or [])
    elif ocr_items is None:
        items = list(null_ocr(image) or [])
    ocr_engine = "provided" if (ocr_items or ocr_fn) else "null_ocr(none)"

    # 2) scale（t4 复用）→ texts_masked 同步产出
    if scale_override is not None:
        if not isinstance(scale_override, dict) or "scale" not in scale_override \
                or "texts_masked" not in scale_override:
            raise ValueError("scale_override 须为 solve_scale 形态 {scale, texts_masked}")
        scale = dict(scale_override["scale"])
        texts_masked = list(scale_override["texts_masked"])
        if not texts_masked and scale.get("anchor", {}).get("type") != "manual":
            raise ValueError("非 manual anchor 缺 texts_masked，不可审计（§6）")
    else:
        solved = solve_scale(items, w, h, source=source)
        scale = solved["scale"]
        texts_masked = solved["texts_masked"]

    # 3) text-mask（铁律第二步：先掩膜再检测）
    masked_img, painted = mask_text_boxes(
        image, [t["bbox_px"] for t in texts_masked], pad=p["mask_pad"])

    # 4) 二值化 + 断线缝合（闭运算，无偏）
    binary = masked_img.threshold(p["thresh"])
    closed = _morph.close(binary, p["gap_radius"])

    # 5) rib 提取（tophat），独立细连通域从几何标记中剔除（防双重计数）
    ribs, rib_mask = extract_ribs(
        closed, rib_se=p["rib_se"], min_len_px=p["rib_min_len_px"],
        max_width_px=p["rib_max_width_px"], min_solidity=p["rib_min_solidity"])
    geo = _morph.subtract(closed, rib_mask)

    # 6) 连通域 + 线框内腔过滤 + 轮廓
    _, fg_comps = label(geo, connectivity=8)
    exterior, enclosed = enclosed_background_components(geo)
    filled, wall_info = stroke_wall_filter(geo, enclosed, exterior,
                                           max_wall_px=p["max_wall_px"])
    loops, loop_info = extract_loops(
        filled, rdp_eps=p["rdp_eps"], min_loop_area_px=p["min_loop_area_px"],
        min_hole_area_px=p["min_hole_area_px"])
    assign_roles(loops)

    # 7) 组装 plan（CAD 系 mm；D2/D3/D4 由 builder 强制）
    builder = PlanBuilder(scale, w, h, source=source or "unknown",
                          tracer=tracer, notes=notes or f"ocr={ocr_engine}")
    builder.set_texts_masked(texts_masked)
    role_count = {}
    for lp in loops:
        role_count[lp["role"]] = role_count.get(lp["role"], 0)
        lid = f"{lp['role']}_{role_count[lp['role']]}"
        role_count[lp["role"]] += 1
        area = lp["area_px"]
        conf = round(area / (area + 50.0), 3)
        builder.add_loop(lp["points_px"], role=lp["role"], confidence=conf,
                         source="stitched", lid=lid)
    for i, rb in enumerate(ribs):
        builder.add_rib(rb["centerline_px"], rb["width_px"],
                        confidence=rb["confidence"], rid=f"rib_{i}")
    plan = builder.build()

    debug = {
        "params": p,
        "ocr_engine": ocr_engine,
        "ocr_count": len(items),
        "masked_boxes": painted,
        "fg_components": len(fg_comps),
        "wall_info": {k: {"wall": v["wall"], "filled": v["filled"]}
                      for k, v in wall_info.items()},
        "loops_px": [{"id": lp["id"], "role": lp["role"], "area_px": lp["area_px"],
                      "points_px": lp["points_px"]} for lp in loops],
        "ribs_px": [{"centerline_px": rb["centerline_px"], "width_px": rb["width_px"],
                     "length_px": rb["length_px"]} for rb in ribs],
        "loop_info": loop_info,
        "warnings": builder.warnings,
    }
    return plan, debug
