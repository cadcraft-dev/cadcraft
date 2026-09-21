"""t4 单测：Jev Choice 分类器（云/本地同 schema + 降级路径）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cadcraft.verifier import jev_judge as jj  # noqa: E402

ITEM_KEYS = {"segment_id", "label", "confidence", "probabilities", "source"}
TOP_KEYS = {"results", "source", "model", "cloud_error"}


def _assert_schema(out):
    assert set(out.keys()) == TOP_KEYS
    for item in out["results"]:
        assert set(item.keys()) == ITEM_KEYS
        assert item["label"] in ("wall", "opening", "noise")
        assert set(item["probabilities"].keys()) == {"wall", "opening", "noise"}
        assert abs(sum(item["probabilities"].values()) - 1.0) < 1e-9
        assert item["confidence"] == item["probabilities"][item["label"]]
        assert item["source"] in ("jev-cloud", "heuristic-local")


def test_heuristic_wall_opening_noise(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    out = jj.classify_segments([
        {"id": "w1", "length_px": 300.0, "width_px": 10.0},
        {"id": "d1", "length_px": 45.0, "width_px": 2.0, "touches_wall": True},
        {"id": "n1", "length_px": 3.0, "width_px": 1.0},
    ])
    _assert_schema(out)
    assert out["source"] == "heuristic-local"
    assert out["cloud_error"] is None
    by_id = {r["segment_id"]: r["label"] for r in out["results"]}
    assert by_id == {"w1": "wall", "d1": "opening", "n1": "noise"}


def test_heuristic_missing_geometry_is_low_conf_noise(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    out = jj.classify_segments([{"id": "x"}])
    _assert_schema(out)
    assert out["results"][0]["label"] == "noise"
    assert out["results"][0]["confidence"] <= 0.5


def test_force_local_same_keys_even_with_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-key")
    out = jj.classify_segments([{"id": "w1", "length_px": 300.0, "width_px": 10.0}],
                               force_local=True)
    _assert_schema(out)
    assert out["source"] == "heuristic-local"


def test_cloud_success_parses_choices(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-key")

    def fake_ask(state, questions, api_key, timeout=30):
        assert "w1" in state and "d1" in state
        assert len(questions) == 2
        return {"answers": {
            "seg_0__w1": {"choice": "wall",
                          "probabilities": {"wall": 0.9, "opening": 0.07, "noise": 0.03}},
            "seg_1__d1": {"choice": "opening",
                          "probabilities": {"wall": 0.1, "opening": 0.8, "noise": 0.1}},
        }}

    monkeypatch.setattr(jj, "jev_ask", fake_ask)
    out = jj.classify_segments([
        {"id": "w1", "length_px": 300.0, "width_px": 10.0},
        {"id": "d1", "length_px": 45.0, "width_px": 2.0},
    ])
    _assert_schema(out)
    assert out["source"] == "jev-cloud" and out["model"] == jj.MODEL
    assert [r["label"] for r in out["results"]] == ["wall", "opening"]
    assert all(r["source"] == "jev-cloud" for r in out["results"])


def test_cloud_failure_falls_back_with_note(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-key")

    def boom(state, questions, api_key, timeout=30):
        raise ConnectionError("dns down")

    monkeypatch.setattr(jj, "jev_ask", boom)
    out = jj.classify_segments([{"id": "w1", "length_px": 300.0, "width_px": 10.0}])
    _assert_schema(out)
    assert out["source"] == "heuristic-local"
    assert "ConnectionError" in (out["cloud_error"] or "")
    assert out["results"][0]["label"] == "wall"  # 启发式仍正常工作


def test_cloud_bad_answer_per_segment_falls_back(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-key")
    monkeypatch.setattr(jj, "jev_ask",
                        lambda s, q, k, timeout=30: {"answers": {"seg_0__w1": {"choice": "roof"}}})
    out = jj.classify_segments([{"id": "w1", "length_px": 300.0, "width_px": 10.0}])
    _assert_schema(out)
    assert out["results"][0]["source"] == "heuristic-local"
    assert out["results"][0]["label"] == "wall"
