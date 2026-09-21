from cadcraft.planner.schema import parse_plan, heuristic_plan_from_text
def test_parse_ref():
    p = parse_plan({"units": "mm", "params": {"L1": 80, "W1": 50}, "steps": [{"op": "rect", "x": 0, "y": 0, "w": "L1", "h": "W1"}]})
    assert p.params["L1"].value == 80
def test_heuristic():
    p = heuristic_plan_from_text("画80x50矩形，中心Φ20孔")
    assert p.params["L1"].value == 80 and p.params["D1"].value == 20
