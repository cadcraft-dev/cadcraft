from __future__ import annotations
"""Local 2D analogue of Pointer-CAD v2 vertex/edge/face checks (unnormalized)."""
def verify(exec_info: dict, plan) -> dict:
    bbox = exec_info.get("bbox_mm", [0, 0, 0, 0])
    w, h = max(1e-9, bbox[2]-bbox[0]), max(1e-9, bbox[3]-bbox[1])
    tol = min(w, h) / 1000.0  # same rule as paper: min edge / 1000
    entities = exec_info.get("entities", [])
    # expected dims from plan params (mm)
    from ..planner.schema import to_mm
    exp = {k: to_mm(v.value, v.unit) for k, v in plan.params.items()}
    checks: list[dict] = []
    # rect size check
    for e in entities:
        if e["op"] == "rect":
            ok_w = abs(e["w"] - exp.get("L1", e["w"])) <= max(tol, 1e-6)
            ok_h = abs(e["h"] - exp.get("W1", e["h"])) <= max(tol, 1e-6)
            checks.append({"name": "rect_size", "passed": bool(ok_w and ok_h),
                           "tol_mm": tol, "detail": f"w={e['w']} h={e['h']} exp L1={exp.get('L1')} W1={exp.get('W1')}"})
        if e["op"] == "hole":
            ok_d = abs(e["d"] - exp.get("D1", e["d"])) <= max(tol, 1e-6)
            checks.append({"name": "hole_diameter", "passed": bool(ok_d),
                           "tol_mm": tol, "detail": f"d={e['d']} exp D1={exp.get('D1')}"})
    # closed-loop check: at least one rect
    checks.append({"name": "has_closed_profile", "passed": any(e["op"] == "rect" for e in entities), "tol_mm": tol, "detail": "need >=1 rect"})
    passed = all(c["passed"] for c in checks) if checks else False
    wrong = sum(1 for c in checks if not c["passed"])
    return {"passed": passed, "tol_mm": tol, "checks": checks,
            "rmr3_repairable": wrong <= 3, "wrong_count": wrong}
