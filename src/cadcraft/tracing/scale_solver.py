"""Scale solver（t4）：用最长 OCR 尺寸反推 px/mm，替代手猜 scale。

契约来源：docs/plan-v02-spec.md §5（Scale Solver 契约）+ §6（anchor/texts_masked 交叉检查）。
输出的 ``scale`` 节点可直接嵌入 Plan v0.2（docs/plan-v02.schema.json），
``texts_masked`` 与 ``scale.anchor.bbox_px`` 满足 §6 逐值相等要求。

算法（冻结决策 D5）：
  1. 解析全部 OCR 尺寸文本 → 数值 + 单位 → 毫米；
  2. 只保留可信项（confidence ≥ 0.5，且 px/真实长度 > 0）；
  3. 取 real_length_mm 最大者为 anchor（最长者相对误差最小），
     ``S = px_length / real_length_mm``（保留 ≥4 位有效数字）；
  4. 无可信尺寸 → ``type=manual`` + ``uncertain=true`` 降级（L2/L3 判不合格，L1 放行）。

本模块纯标准库、无第三方依赖，方便 t2（tracer）直接调用。
"""

from __future__ import annotations

import math
import re

# 可信 anchor 的最低置信度（spec §5：confidence ≥ 0.5）。
MIN_ANCHOR_CONFIDENCE = 0.5

# 无 anchor 时的降级 px/mm（v0.1 遗留手填常量，仅占位，必须配合 uncertain=true 使用）。
FALLBACK_PX_PER_MM = 3.78

# 用 bbox 长边代理 px_length 时的置信度惩罚系数（有文档、可审计）。
BBOX_PROXY_CONFIDENCE_PENALTY = 0.8

# 单位 → mm 换算。
_UNIT_TO_MM = {
    "mm": 1.0,
    "millimeter": 1.0,
    "millimeters": 1.0,
    "cm": 10.0,
    "centimeter": 10.0,
    "centimeters": 10.0,
    "m": 1000.0,
    "meter": 1000.0,
    "meters": 1000.0,
}

# 尺寸文本解析：可选直径/半径/螺纹前缀 + 数字 + 可选单位。
# 例："120" "120mm" "12cm" "1.2m" "Ø20" "Φ20" "φ20" "R10" "M10" "120 MM"。
_DIM_RE = re.compile(
    r"""^\s*
        [ØΦφøRrMm]?\s*            # 可选前缀：直径/半径/螺纹标记
        (?P<num>\d+(?:\.\d+)?)    # 数值
        \s*(?P<unit>mm|millimeters?|cm|centimeters?|m|meters?)?  # 可选单位，默认 mm
        \s*$""",
    re.VERBOSE | re.IGNORECASE,
)


def parse_dimension_text(text: str) -> float | None:
    """把 OCR 尺寸文本解析为毫米数，失败返回 None。

    - 无单位默认 mm；cm ×10；m ×1000。
    - 允许 ``Ø/Φ/φ/R/M`` 前缀（直径/半径/螺纹），只取数值部分。
    - 非尺寸文本（如 "ABC"、空串、负数）返回 None。
    """
    if not isinstance(text, str):
        return None
    m = _DIM_RE.match(text.strip())
    if not m:
        return None
    try:
        value = float(m.group("num"))
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    unit = (m.group("unit") or "mm").lower()
    factor = _UNIT_TO_MM.get(unit)
    if factor is None:
        return None
    result = value * factor
    if not math.isfinite(result) or result <= 0:
        return None
    return result


def _norm_bbox_px(bbox_px, *, where: str) -> list[float]:
    """校验并规范 OCR bbox 为 [x0, y0, x1, y1]（x1>x0, y1>y0）。

    允许坐标写反（自动按 min/max 归位）；退化 bbox（零面积/非数字）直接
    ``ValueError``，不编造占位坐标——下游 plan_io 会执行同样的严格校验。
    """
    try:
        vals = [float(v) for v in bbox_px]
    except (TypeError, ValueError):
        raise ValueError(f"{where}: bbox_px 须为 4 个数字，got {bbox_px!r}")
    if len(vals) != 4 or not all(math.isfinite(v) for v in vals):
        raise ValueError(f"{where}: bbox_px 须为 4 个有限数字，got {bbox_px!r}")
    x0, y0, x1, y1 = vals
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    if not (x1 > x0 and y1 > y0):
        raise ValueError(f"{where}: bbox_px 退化（零面积），got {bbox_px!r}")
    return [x0, y0, x1, y1]


def _round_sig(value: float, sig: int = 4) -> float:
    """保留 ≥sig 位有效数字（spec §5 精度要求）。"""
    if value <= 0 or not math.isfinite(value):
        raise ValueError(f"px_per_mm must be positive finite, got {value!r}")
    return float(f"{value:.{sig}g}")


def solve_scale(
    ocr_items,
    image_width_px: int,
    image_height_px: int,
    source: str = "",
) -> dict:
    """由 OCR 尺寸列表反推 scale，返回 ``{"scale": ..., "texts_masked": [...]}``。

    :param ocr_items: 每项 ``{"text": str, "bbox_px": [x0,y0,x1,y1],
        "px_length": float(可选, dimension线实测像素长),
        "confidence": float(可选, 默认 1.0)}``。
    :param image_width_px: 计算 S 时所用的图宽（必须与 plan.image 一致）。
    :param image_height_px: 图高。
    :param source: 仅用于文档说明，不进入输出。
    :return: ``{"scale": {"px_per_mm", "anchor", "uncertain"},
        "texts_masked": [{"text", "bbox_px", "used_as_anchor"}]}``。
        有 anchor 时 ``uncertain=false``；无可信尺寸时 manual 降级
        ``uncertain=true``（L2/L3 不可用，见 spec §5）。
    """
    if not isinstance(image_width_px, int) or image_width_px < 1:
        raise ValueError(f"image_width_px must be positive int, got {image_width_px!r}")
    if not isinstance(image_height_px, int) or image_height_px < 1:
        raise ValueError(f"image_height_px must be positive int, got {image_height_px!r}")

    items = list(ocr_items or [])
    texts_masked: list[dict] = []
    candidates: list[dict] = []

    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text", ""))
        bbox = _norm_bbox_px(raw.get("bbox_px", []), where=f"ocr_items[{idx}]")
        try:
            conf = float(raw.get("confidence", 1.0))
        except (TypeError, ValueError):
            conf = 0.0
        if not math.isfinite(conf):
            conf = 0.0
        conf = min(max(conf, 0.0), 1.0)

        real_mm = parse_dimension_text(text)

        # px_length：优先用实测 dimension 线长，缺失时用 bbox 长边代理并惩罚置信度。
        px_length = raw.get("px_length", None)
        try:
            px_length = float(px_length) if px_length is not None else None
        except (TypeError, ValueError):
            px_length = None
        if px_length is None or not math.isfinite(px_length) or px_length <= 0:
            px_length = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
            conf *= BBOX_PROXY_CONFIDENCE_PENALTY

        texts_masked.append(
            {"text": text, "bbox_px": list(bbox), "used_as_anchor": False}
        )
        if real_mm is not None and conf >= MIN_ANCHOR_CONFIDENCE:
            candidates.append(
                {
                    "text": text,
                    "bbox_px": list(texts_masked[-1]["bbox_px"]),
                    "real_length_mm": real_mm,
                    "px_length": float(px_length),
                    "confidence": conf,
                }
            )

    if candidates:
        # D5：取最长可信尺寸；并列时置信度高者优先，再并列取 px 更长者。
        candidates.sort(
            key=lambda c: (c["real_length_mm"], c["confidence"], c["px_length"]),
            reverse=True,
        )
        win = candidates[0]
        px_per_mm = _round_sig(win["px_length"] / win["real_length_mm"])
        anchor = {
            "type": "dimension",
            "ocr_text": win["text"],
            "real_length_mm": float(win["real_length_mm"]),
            "px_length": float(win["px_length"]),
            "bbox_px": list(win["bbox_px"]),
            "confidence": float(win["confidence"]),
        }
        for entry in texts_masked:
            if (
                entry["text"] == win["text"]
                and list(entry["bbox_px"]) == list(win["bbox_px"])
                and not entry["used_as_anchor"]
            ):
                entry["used_as_anchor"] = True
                break
        scale = {"px_per_mm": px_per_mm, "anchor": anchor, "uncertain": False}
    else:
        # 降级：manual + uncertain=true（spec §5；L2/L3 verifier 必须 FAIL 此类 plan）。
        anchor = {
            "type": "manual",
            "ocr_text": "",
            "real_length_mm": 1.0,
            "px_length": float(FALLBACK_PX_PER_MM),
            "confidence": 0.0,
        }
        scale = {
            "px_per_mm": float(FALLBACK_PX_PER_MM),
            "anchor": anchor,
            "uncertain": True,
        }

    return {"scale": scale, "texts_masked": texts_masked}


def verify_anchor_consistency(scale: dict, texts_masked: list) -> tuple[bool, str]:
    """§6 交叉检查：anchor 文本的 bbox 必须逐值等于某条 used_as_anchor 的 mask 记录。

    :return: ``(ok, reason)``。manual anchor 无需交叉检查，直接通过。
    """
    if not isinstance(scale, dict) or not isinstance(scale.get("anchor"), dict):
        return False, "scale.anchor 缺失"
    anchor = scale["anchor"]
    if anchor.get("type") == "manual":
        if scale.get("uncertain") is not True:
            return False, "manual anchor 必须同时 uncertain=true"
        return True, "manual anchor 无需交叉检查"
    if anchor.get("type") not in ("dimension", "bar"):
        return False, f"未知 anchor type: {anchor.get('type')!r}"
    want_bbox = list(anchor.get("bbox_px", []) or [])
    want_text = anchor.get("ocr_text", "")
    if len(want_bbox) != 4:
        return False, "dimension/bar anchor 必须携带 bbox_px"
    for entry in texts_masked or []:
        if not isinstance(entry, dict) or entry.get("used_as_anchor") is not True:
            continue
        got_bbox = list(entry.get("bbox_px", []) or [])
        if len(got_bbox) == 4 and entry.get("text") == want_text and all(
            float(a) == float(b) for a, b in zip(got_bbox, want_bbox)
        ):
            return True, "anchor 与 texts_masked 交叉检查通过"
    return False, "anchor bbox/text 在 texts_masked 中找不到逐值相等的 used_as_anchor 记录（疑似编造 scale）"


def px_to_mm(x_px: float, y_px: float, scale: dict, image_height_px: int) -> tuple[float, float]:
    """图像系（左上原点，y 向下）→ CAD 系（x 右 y 上，mm）。spec §4.2 D1。

    ``x_mm = x_px / S``，``y_mm = (H_px - y_px) / S``。
    """
    s = float(scale["px_per_mm"])
    if s <= 0 or not math.isfinite(s):
        raise ValueError(f"illegal px_per_mm: {s!r}")
    return float(x_px) / s, (float(image_height_px) - float(y_px)) / s
