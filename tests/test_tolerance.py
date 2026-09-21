from cadcraft.planner.schema import heuristic_plan_from_text
from cadcraft.verifier.tolerance import verify
def test_tol_pass():
    plan = heuristic_plan_from_text("80x50 Φ20")
    exec_info = {"entities": [{"op": "rect", "x": 0, "y": 0, "w": 80, "h": 50}, {"op": "hole", "cx": 40, "cy": 25, "d": 20}], "bbox_mm": [0, 0, 80, 50]}
    r = verify(exec_info, plan)
    assert r["passed"] and r["tol_mm"] == 0.05
def test_tol_fail():
    plan = heuristic_plan_from_text("80x50 Φ20")
    exec_info = {"entities": [{"op": "rect", "x": 0, "y": 0, "w": 80.5, "h": 50}], "bbox_mm": [0, 0, 80.5, 50]}
    assert not verify(exec_info, plan)["passed"]
