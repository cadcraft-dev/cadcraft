"""Executor tests (t3): one multi-loop plan → many DXF entities.

Anti-R1: the file must hold one closed LWPOLYLINE per loop on role
layers, rib centerlines with width on RIBS, audit rects on TEXT_MASK —
never a single merged rectangle. Units must be mm.
"""

import os

import pytest

from cadcraft.executor.dxf import plan_to_dxf, read_dxf_summary
from cadcraft.plan_io import PlanError

from helpers_v02 import make_plan, make_single_rect_plan

TMP = os.path.join(os.path.dirname(__file__), "tmp")


def _out(name):
    os.makedirs(TMP, exist_ok=True)
    return os.path.join(TMP, name)


def test_multiloop_plan_exports_one_entity_per_loop():
    summary = plan_to_dxf(make_plan(), _out("bracket.dxf"))
    assert set(summary["loops"]) == {"outer_0", "hole_0"}
    assert summary["loops"]["outer_0"]["layer"] == "OUTER"
    assert summary["loops"]["hole_0"]["layer"] == "HOLES"
    assert summary["ribs"]["rib_0"]["layer"] == "RIBS"
    assert summary["ribs"]["rib_0"]["width_mm"] == pytest.approx(6.0)
    assert summary["texts"] == 1

    back = read_dxf_summary(_out("bracket.dxf"))
    assert back["insunits"] == 4  # mm
    assert back["per_layer"].get("OUTER") == 1
    assert back["per_layer"].get("HOLES") == 1
    assert back["per_layer"].get("RIBS") == 1
    assert back["per_layer"].get("TEXT_MASK") == 1
    assert back["total_lwpolylines"] == 4
    assert all(back["closed_flags"][:2])  # loops closed
    assert not back["closed_flags"][2]  # rib centerline open
    assert max(back["const_widths"]) == pytest.approx(6.0)


def test_notch_gets_own_layer_entity():
    summary = plan_to_dxf(make_plan(loops="outer+hole+notch"), _out("notch.dxf"))
    assert summary["loops"]["notch_0"]["layer"] == "NOTCH"
    back = read_dxf_summary(_out("notch.dxf"))
    assert back["per_layer"].get("NOTCH") == 1
    assert back["total_lwpolylines"] == 5


def test_single_rect_plan_exports_single_entity():
    """Documents the spoof shape: the executor is faithful, the verifier
    must reject it (see test_verifier_hardening negative control)."""
    summary = plan_to_dxf(make_single_rect_plan(), _out("spoof.dxf"))
    assert len(summary["loops"]) == 1
    back = read_dxf_summary(_out("spoof.dxf"))
    assert back["total_lwpolylines"] == 2  # 1 loop + 1 text-mask rect


def test_illegal_plan_raises_not_silent():
    bad = make_plan()
    bad["loops"] = []  # violates minItems 1
    with pytest.raises(PlanError):
        plan_to_dxf(bad, _out("bad.dxf"))


def test_explicit_repeat_point_is_deduped():
    plan = make_plan()
    plan["loops"][0]["points"] = plan["loops"][0]["points"] + [[0, 0]]
    summary = plan_to_dxf(plan, _out("repeat.dxf"))
    assert summary["loops"]["outer_0"]["vertices"] == 6
