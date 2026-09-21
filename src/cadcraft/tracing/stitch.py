"""P1: segments + OCR texts -> Plan (rules v0.1 + sanity guard)."""
from __future__ import annotations
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
