from __future__ import annotations
from dataclasses import dataclass, field
import json, re

@dataclass
class PlanParam:
    name: str  # L1, W1, D1, A1...
    value: float
    unit: str = "mm"
    expr: str | None = None  # e.g. "2*L1"

@dataclass
class PlanStep:
    op: str  # rect | circle | hole | fillet | dim | text
    params: dict = field(default_factory=dict)
    layer: str = "0"

@dataclass
class Plan:
    units: str = "mm"
    params: dict[str, PlanParam] = field(default_factory=dict)
    steps: list[PlanStep] = field(default_factory=list)
    notes: str = ""

PLAN_JSON_SCHEMA = {
  "type": "object",
  "required": ["units", "params", "steps"],
  "properties": {
    "units": {"type": "string", "enum": ["mm", "cm", "m", "inch"]},
    "params": {"type": "object"},
    "steps": {"type": "array"},
  },
}

_UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4}

def to_mm(value: float, unit: str) -> float:
    return float(value) * _UNIT_TO_MM.get(unit, 1.0)

_DIM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mm|cm|m|inch|Φ|φ|R)?")

def parse_plan(obj: dict) -> Plan:
    units = obj.get("units", "mm")
    params: dict[str, PlanParam] = {}
    for k, v in (obj.get("params") or {}).items():
        if isinstance(v, (int, float)):
            params[k] = PlanParam(name=k, value=float(v), unit=units)
        elif isinstance(v, dict):
            params[k] = PlanParam(name=k, value=float(v.get("value", 0)),
                                  unit=v.get("unit", units), expr=v.get("expr"))
        else:
            raise ValueError(f"bad param {k}={v!r}")
    # resolve simple refs like {"value": "2*L1"} without eval
    resolved = dict(params)
    for k, p in list(params.items()):
        if isinstance(p.value, str):  # type: ignore
            expr = str(p.value)
            m = re.fullmatch(r"\s*([\d.]+)\s*\*\s*([A-Za-z]\w*)\s*", expr)
            if m and m.group(2) in resolved:
                mult = float(m.group(1))
                base = resolved[m.group(2)].value
                resolved[k] = PlanParam(name=k, value=mult * float(base), unit=p.unit, expr=expr)
    steps = [PlanStep(op=s.get("op", ""), params={kk: vv for kk, vv in s.items() if kk not in ("op", "layer")}, layer=s.get("layer", "0")) for s in obj.get("steps", [])]
    return Plan(units=units, params=resolved, steps=steps, notes=obj.get("notes", ""))

def heuristic_plan_from_text(text: str) -> Plan:
    """Deterministic fallback when Ollama is unavailable: extract numbers like 80x50, Φ20, R5."""
    t = text.replace("×", "x").replace("Ｘ", "x")
    nums = re.findall(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", t)
    dia = re.search(r"[Φφ]\s*(\d+(?:\.\d+)?)", t)
    rfil = re.search(r"R\s*(\d+(?:\.\d+)?)", t)
    params: dict[str, PlanParam] = {}
    steps: list[PlanStep] = []
    if nums:
        L, W = float(nums[0][0]), float(nums[0][1])
        params["L1"] = PlanParam("L1", L); params["W1"] = PlanParam("W1", W)
        p: dict = {"x": 0, "y": 0, "w": "L1", "h": "W1"}
        if rfil:
            params["R1"] = PlanParam("R1", float(rfil.group(1)))
            p["r"] = "R1"
        steps.append(PlanStep(op="rect", params=p))
    if dia:
        params["D1"] = PlanParam("D1", float(dia.group(1)))
        steps.append(PlanStep(op="hole_center_rect", params={"d": "D1"}))
    if not steps:  # default demo part
        params = {"L1": PlanParam("L1", 80), "W1": PlanParam("W1", 50), "D1": PlanParam("D1", 20)}
        steps = [PlanStep(op="rect", params={"x": 0, "y": 0, "w": "L1", "h": "W1"}),
                 PlanStep(op="hole_center_rect", params={"d": "D1"})]
    return Plan(units="mm", params=params, steps=steps, notes=f"heuristic from: {text[:120]}")

def plan_to_json(plan: Plan) -> str:
    return json.dumps({"units": plan.units,
        "params": {k: {"value": v.value, "unit": v.unit} for k, v in plan.params.items()},
        "steps": [{"op": s.op, **s.params, "layer": s.layer} for s in plan.steps],
        "notes": plan.notes}, ensure_ascii=False, indent=2)
