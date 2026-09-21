"""Example: re-verify an existing plan/exec with Jev (advisory)."""
import argparse, json
from cadcraft.verifier import jev_score
ap = argparse.ArgumentParser()
ap.add_argument("--dxf", default="/tmp/demo.dxf")
a = ap.parse_args()
fake_exec = {"dxf": a.dxf, "entities": [{"op": "rect", "x": 0, "y": 0, "w": 80, "h": 50}], "bbox_mm": [0, 0, 80, 50]}
fake_tol = {"passed": True, "tol_mm": 0.05, "rmr3_repairable": True}
r = jev_score("这张图尺寸可交付吗？", fake_exec, fake_tol)
print(json.dumps({"kind": r.kind, "value": r.value, "confidence": r.confidence}, ensure_ascii=False, indent=2))
