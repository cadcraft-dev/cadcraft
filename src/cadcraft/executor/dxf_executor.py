from __future__ import annotations
from ..planner.schema import Plan, to_mm

def resolve(v, plan: Plan) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v in plan.params:
        p = plan.params[v]
        return to_mm(p.value, p.unit or plan.units)
    return float(v)

def execute_plan_to_dxf(plan: Plan, out_path: str) -> dict:
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    # find base rect for centering holes
    base = None
    log: list[dict] = []
    for s in plan.steps:
        if s.op == "rect":
            x, y = resolve(s.params.get("x", 0), plan), resolve(s.params.get("y", 0), plan)
            w, h = resolve(s.params["w"], plan), resolve(s.params["h"], plan)
            r = s.params.get("r")
            if r is not None:
                rr = resolve(r, plan)
                msp.add_lwpolyline([(x+rr, y), (x+w-rr, y), (x+w, y+rr), (x+w, y+h-rr),
                                    (x+w-rr, y+h), (x+rr, y+h), (x, y+h-rr), (x, y+rr)],
                                   close=True)
            else:
                msp.add_lwpolyline([(x, y), (x+w, y), (x+w, y+h), (x, y+h)], close=True)
            base = (x, y, w, h)
            log.append({"op": "rect", "x": x, "y": y, "w": w, "h": h})
        elif s.op == "circle":
            cx, cy = resolve(s.params.get("cx", 0), plan), resolve(s.params.get("cy", 0), plan)
            d = s.params.get("d", s.params.get("r"))
            r = resolve(d, plan) / (1.0 if "r" in s.params else 2.0)
            msp.add_circle((cx, cy), r)
            log.append({"op": "circle", "cx": cx, "cy": cy, "r": r})
        elif s.op == "hole_center_rect":
            assert base, "hole_center_rect needs a base rect first"
            x, y, w, h = base
            d = resolve(s.params["d"], plan)
            msp.add_circle((x + w/2, y + h/2), d/2)
            log.append({"op": "hole", "cx": x+w/2, "cy": y+h/2, "d": d})
        elif s.op == "dim":
            pass  # v0.1: dimensions added in v0.2 with styles
        else:
            log.append({"op": f"ignored:{s.op}"})
    doc.saveas(out_path)
    # bbox in mm (plan already resolved to mm)
    xs, ys = [], []
    for e in log:
        if e["op"] == "rect":
            xs += [e["x"], e["x"]+e["w"]]; ys += [e["y"], e["y"]+e["h"]]
        if e["op"] in ("circle", "hole"):
            r = e.get("r", e.get("d", 0)/2)
            xs += [e["cx"]-r, e["cx"]+r]; ys += [e["cy"]-r, e["cy"]+r]
    bbox = [min(xs or [0]), min(ys or [0]), max(xs or [0]), max(ys or [0])]
    return {"dxf": out_path, "entities": log, "bbox_mm": bbox}
