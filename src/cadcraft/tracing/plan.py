"""Plan v0.2 组装器（spec §4）：像素系检测结果 → CAD 系 plan dict。

- 坐标变换与 anchor 交叉检查**复用 t4 scale_solver**（px_to_mm /
  verify_anchor_consistency），本模块不再重复实现 scale 逻辑；
- build() 强制执行 spec D2（闭合 ≤0.05mm、自交拒收）/ D3（outer-CCW、hole-CW，
  自动纠正）/ D4（Σhole < 50% outer）/ 恰好一个 outer；
- v01_upgrade：v0.1 → v0.2 读取兼容（polygon→outer 单 loop，scale→manual+uncertain）；
- texts_masked/scale 由调用方（pipeline 经 solve_scale）传入，builder 只做
  一致性校验，不伪造。
"""

from __future__ import annotations

import math

from .geometry import is_simple_polygon, signed_area
from .scale_solver import px_to_mm, verify_anchor_consistency

LOOP_ROLES = ("outer", "hole", "notch", "detail")

CLOSURE_TOL_MM = 0.05  # D2
HOLE_AREA_RATIO_MAX = 0.5  # D4


class PlanError(ValueError):
    """plan 非法（D2/D3/D4/§8.3 结构性违规）。"""


def _loop_area(points_mm) -> float:
    return abs(signed_area(points_mm))


def _check_winding(points_mm, role: str):
    """D3：CAD 系（y 向上）outer 须 CCW（area>0），hole 须 CW；反了自动纠正。"""
    area = signed_area(points_mm)
    if area == 0:
        raise PlanError(f"{role}: 退化 loop（面积为 0）")
    if role == "outer" and area < 0:
        return [list(p) for p in reversed(points_mm)], True
    if role == "hole" and area > 0:
        return [list(p) for p in reversed(points_mm)], True
    return [list(p) for p in points_mm], False


class PlanBuilder:
    """逐项累加强制校验的 v0.2 组装器。scale/texts_masked 构造时注入。"""

    def __init__(self, scale: dict, image_width_px: int, image_height_px: int,
                 source: str = "", tracer: str = "t2-stitch", notes: str = ""):
        if not isinstance(scale, dict) or scale.get("px_per_mm", 0) <= 0:
            raise PlanError(f"illegal scale: {scale!r}")
        self.scale = scale
        self.w, self.h = int(image_width_px), int(image_height_px)
        self.source = source
        self.tracer = tracer
        self.notes = notes
        self._loops = []
        self._ribs = []
        self._texts_masked = []
        self.warnings = []

    def set_texts_masked(self, texts_masked) -> None:
        self._texts_masked = [dict(t) for t in texts_masked or []]

    def px_to_mm_pt(self, x_px, y_px):
        return list(px_to_mm(x_px, y_px, self.scale, self.h))

    def add_loop(self, points_px, role: str, confidence: float = 0.0,
                 source: str = "detected", lid: str = None):
        if role not in LOOP_ROLES:
            raise PlanError(f"illegal role: {role!r}")
        pts_px = [[float(p[0]), float(p[1])] for p in points_px]
        if len(pts_px) < 3:
            raise PlanError(f"{role}: 点数 <3")
        pts_mm = [self.px_to_mm_pt(x, y) for x, y in pts_px]
        # D2 闭合：显式重复（首≈尾）去重；隐式环（边回绕）按定义即闭合，
        # 与 verifier plan_io.loop_closure_ok 同语义（见 cadcraft.geometry）。
        gap = math.hypot(pts_mm[0][0] - pts_mm[-1][0], pts_mm[0][1] - pts_mm[-1][1])
        ring = pts_mm[:-1] if gap <= CLOSURE_TOL_MM else pts_mm
        if len(ring) < 3:
            raise PlanError(f"{role}: 去重后点数 <3")
        if not is_simple_polygon(ring):
            raise PlanError(f"{role}: 自交多边形非法")
        pts_mm, fixed = _check_winding(ring, role)
        if fixed:
            self.warnings.append(f"{role}: 环绕方向已自动纠正")
        try:
            conf = float(confidence)
        except (TypeError, ValueError):
            conf = 0.0
        self._loops.append({
            "id": lid or f"{role}_{sum(1 for l in self._loops if l['role'] == role)}",
            "role": role,
            "points": [[round(x, 4), round(y, 4)] for x, y in pts_mm],
            "closed": True,
            "area_mm2": round(_loop_area(pts_mm), 4),
            "confidence": min(max(conf, 0.0), 1.0),
            "source": source,
        })
        return self._loops[-1]["id"]

    def add_rib(self, centerline_px, width_px: float, confidence: float = 0.0,
                extends_mm=None, rid: str = None):
        cl = [[float(p[0]), float(p[1])] for p in centerline_px]
        if len(cl) < 2:
            raise PlanError("rib: centerline 点数 <2")
        if width_px <= 0:
            raise PlanError("rib: width 必须 >0")
        cl_mm = [self.px_to_mm_pt(x, y) for x, y in cl]
        s = float(self.scale["px_per_mm"])
        self._ribs.append({
            "id": rid or f"rib_{len(self._ribs)}",
            "centerline": [[round(x, 4), round(y, 4)] for x, y in cl_mm],
            "width_mm": round(float(width_px) / s, 4),
            "extends_mm": [float(extends_mm[0]), float(extends_mm[1])]
            if extends_mm else [0.0, 0.0],
            "confidence": min(max(float(confidence), 0.0), 1.0),
        })
        return self._ribs[-1]["id"]

    def build(self) -> dict:
        outers = [l for l in self._loops if l["role"] == "outer"]
        if len(outers) != 1:
            raise PlanError(f"必须恰好 1 个 outer，实得 {len(outers)}")
        holes = [l for l in self._loops if l["role"] == "hole"]
        if holes:
            ratio = sum(h["area_mm2"] for h in holes) / outers[0]["area_mm2"]
            if ratio >= HOLE_AREA_RATIO_MAX:  # D4
                raise PlanError(f"Σhole/outer={ratio:.3f} ≥ {HOLE_AREA_RATIO_MAX}")
        ok, reason = verify_anchor_consistency(self.scale, self._texts_masked)
        if not ok:
            raise PlanError(f"anchor 交叉检查失败：{reason}")
        plan = {
            "version": "0.2",
            "units": "mm",
            "image": {"width_px": self.w, "height_px": self.h, "source": self.source},
            "scale": {
                "px_per_mm": self.scale["px_per_mm"],
                "anchor": dict(self.scale["anchor"]),
                "uncertain": bool(self.scale.get("uncertain", False)),
            },
            "loops": self._loops,
            "ribs": self._ribs,
            "texts_masked": self._texts_masked,
            "meta": {"tracer": self.tracer, "notes": self.notes,
                     "warnings": self.warnings},
        }
        return plan


def v01_upgrade(v01: dict, image_width_px: int, image_height_px: int,
                source: str = "") -> dict:
    """v0.1 读取兼容（spec §4.5）：polygon→outer 单 loop；scale→manual+uncertain。

    升级产物仅满足 L1 形态；L2/L3 验收按 §8.3 照例 FAIL（anchor=manual）。
    """
    from .scale_solver import FALLBACK_PX_PER_MM

    s = float(v01.get("scale_px_per_mm", FALLBACK_PX_PER_MM))
    builder = PlanBuilder(
        scale={"px_per_mm": s,
               "anchor": {"type": "manual", "ocr_text": "",
                          "real_length_mm": 1.0, "px_length": s, "confidence": 0.0},
               "uncertain": True},
        image_width_px=image_width_px, image_height_px=image_height_px,
        source=source or v01.get("source", ""), tracer="v01-upgrade",
        notes="upgraded from Plan v0.1")
    builder.set_texts_masked([])
    builder.add_loop(v01["polygon"], role="outer", confidence=0.5, source="v01")
    return builder.build()
