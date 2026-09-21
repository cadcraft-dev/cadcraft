"""t5 bench 门限测试（spec §8 发布门，跑真实管线 + 真实 verifier）。

- L1：三矩形全 PASS；v0.1 最优手测基线亦全 PASS → 不退化。
- L2：L2a 3/3、L2b 4/4；平均 recall ≥0.90，单 case ≥0.80。
- 负对照：单矩形冒充必 FAIL，且 bbox-IoU 陷阱 >0.80（反 R5）。
- L3a：参考级——recall ≥0.80 且报告合规（verifier 无 L3 专属推理，见 N3）。
- scale 实测：L2/L3 全为 dimension anchor（非手猜），uncertain=False。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bench"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import bench_lib as B  # noqa: E402
from cadcraft.plan_io import load_plan  # noqa: E402
from cadcraft.verifier.verifier import (  # noqa: E402
    check_report_conformance,
    verify_plan,
)


def _conformant(report):
    ok, problems = check_report_conformance(report)
    assert ok, problems


def test_l1_all_pass():
    for case in B.l1_cases():
        plan, report = B.run_case(case)
        _conformant(report)
        assert report["verdict"] == "PASS", (case["name"], report["reasons"])
        assert report["recall_detail"] == {"recalled": 1, "total": 1}
        assert report["level"] == "L1"


def test_l1_no_regression_vs_v01():
    v01_pass = v02_pass = 0
    for case in B.l1_cases():
        _, v02 = B.run_case(case)
        v02_pass += v02["verdict"] == "PASS"
        v01 = verify_plan(load_plan(B.build_v01_baseline(case)),
                          case["gt"], level="auto")
        v01_pass += v01["verdict"] == "PASS"
    assert (v01_pass, v02_pass) == (3, 3)
    assert v02_pass >= v01_pass  # §8.1：不得低于基线


def test_l2_recall_gates():
    recalls = {}
    for build in (B.build_l2a, B.build_l2b):
        case = build()
        plan, report = B.run_case(case)
        _conformant(report)
        assert report["verdict"] == "PASS", (case["name"], report["reasons"])
        recalls[case["name"]] = report["recall"]
    assert recalls == {"L2a": 1.0, "L2b": 1.0}
    assert sum(recalls.values()) / len(recalls) >= 0.90  # §8.2 平均
    assert min(recalls.values()) >= 0.80                 # §8.2 单 case


def test_l2_scale_is_solved_not_guessed():
    for build in (B.build_l2a, B.build_l2b, B.build_l3):
        case = build()
        plan, report = B.run_case(case)
        assert plan["scale"]["anchor"]["type"] == "dimension"
        assert plan["scale"]["uncertain"] is False
        assert (report["scale_error_pct"] or 0) <= 2.0  # §7.3


def test_negative_control_single_rect_fails():
    neg = B.build_spoof_l2a()
    report = verify_plan(neg["plan"], neg["gt"], level="auto")
    _conformant(report)
    assert report["verdict"] == "FAIL"
    assert any("single_outer_spoof" in h for h in report["hard_fails"])
    assert (report["bbox_iou_advisory"] or 0) > 0.80  # 高 bbox 下仍 FAIL（反 R5）


def test_l3_reference_recall_and_conformance():
    case = B.build_l3()
    _, report = B.run_case(case)
    _conformant(report)
    assert report["recall"] >= 0.80
    assert report["recall_detail"] == {"recalled": 5, "total": 6}
