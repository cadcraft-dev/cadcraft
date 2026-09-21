"""t5 bench 总控：实测全部 case → 落盘 DXF + preview PNG + report.json。

用法（py3.12，有 ezdxf/PIL/pytest）：
    /opt/homebrew/opt/python@3.12/bin/python3.12 bench/run_bench.py

产物：
    bench/out/dxf/<case>.dxf      每 case 的多实体 DXF（含负对照）
    bench/out/preview/<case>.png  左=输入图，右=plan 叠加（角色配色）
    bench/out/report.json         全部 verdict/recall/门限判定 + 已知缺口
"""

from __future__ import annotations

import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import bench_lib as B  # noqa: E402
from cadcraft.executor.dxf import plan_to_dxf  # noqa: E402
from cadcraft.plan_io import load_plan  # noqa: E402
from cadcraft.verifier.verifier import check_report_conformance, verify_plan  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
DXF_DIR = os.path.join(OUT, "dxf")
PREV_DIR = os.path.join(OUT, "preview")

ROLE_COLORS = {"outer": (0, 160, 0), "hole": (220, 0, 0),
               "notch": (220, 140, 0), "detail": (200, 180, 0)}


def gray_to_pil(image):
    from PIL import Image

    im = Image.new("L", (image.width, image.height))
    im.putdata([v for row in image.pixels for v in row])
    return im.convert("RGB")


def draw_overlay(case, plan):
    """右图：plan loop/rib 按角色配色画回像素系（用 plan 自身 S 对齐输入图）。"""
    from PIL import Image, ImageDraw

    img = case["image"]
    s = float(plan["scale"]["px_per_mm"])
    base = gray_to_pil(img)
    ov = Image.new("RGB", (img.width, img.height), (255, 255, 255))
    dr = ImageDraw.Draw(ov)
    for loop in plan["loops"]:
        pts = [(x * s, img.height - y * s) for x, y in loop["points"]]
        dr.polygon(pts, outline=ROLE_COLORS.get(loop["role"], (0, 0, 0)))
    for rib in plan.get("ribs", []):
        pts = [(x * s, img.height - y * s) for x, y in rib["centerline"]]
        dr.line(pts, fill=(0, 0, 220), width=max(1, int(round(rib["width_mm"] * s))))
    return base, ov


def save_preview(case, plan, report):
    from PIL import Image, ImageDraw

    base, ov = draw_overlay(case, plan)
    w, h = base.size
    combo = Image.new("RGB", (w * 2 + 8, h + 26), (240, 240, 240))
    combo.paste(base, (0, 26))
    combo.paste(ov, (w + 8, 26))
    dr = ImageDraw.Draw(combo)
    dr.text((6, 6), f"{case['name']} expect={case['expect']} "
                    f"verdict={report['verdict']} "
                    f"recall={report['recall_detail']['recalled']}/"
                    f"{report['recall_detail']['total']}", fill=(0, 0, 0))
    path = os.path.join(PREV_DIR, f"{case['name']}.png")
    combo.save(path)
    return path


def case_record(case, plan, report, dxf_path, prev_path):
    ok, problems = check_report_conformance(report)
    return {
        "name": case["name"], "level": case["level"], "expect": case["expect"],
        "verdict": report["verdict"], "recall": report["recall"],
        "recall_detail": report["recall_detail"],
        "per_loop": report["per_loop"], "ribs": report["ribs"],
        "scale_error_pct": report["scale_error_pct"],
        "bbox_iou_advisory": report["bbox_iou_advisory"],
        "hard_fails": report["hard_fails"], "warnings": report["warnings"],
        "reasons": report["reasons"],
        "report_conformant": ok, "conformance_problems": problems,
        "scale": {"px_per_mm": plan["scale"]["px_per_mm"],
                  "anchor_type": plan["scale"]["anchor"]["type"],
                  "uncertain": plan["scale"]["uncertain"]},
        "dxf": os.path.relpath(dxf_path, OUT),
        "preview": os.path.relpath(prev_path, OUT),
    }


def main() -> int:
    os.makedirs(DXF_DIR, exist_ok=True)
    os.makedirs(PREV_DIR, exist_ok=True)
    records = []

    traced = [(c, *B.run_case(c)) for c in
              (B.l1_cases() + [B.l1_manual_case(), B.build_l2a(),
                               B.build_l2b(), B.build_l3()])]
    for case, plan, report in traced:
        dxf = plan_to_dxf(plan, os.path.join(DXF_DIR, f"{case['name']}.dxf"))
        prev = save_preview(case, plan, report)
        records.append(case_record(case, plan, report, dxf["path"], prev))

    neg = B.build_spoof_l2a()
    neg_report = verify_plan(neg["plan"], neg["gt"], level="auto")
    neg_dxf = plan_to_dxf(neg["plan"], os.path.join(DXF_DIR, "L2-neg.dxf"))
    neg_prev_case = {"name": "L2-neg", "image": B.build_l2a()["image"]}
    neg_prev = save_preview({**neg_prev_case, "expect": neg["expect"]},
                            neg["plan"], neg_report)
    records.append(case_record({**neg, "level": "L2"}, neg["plan"],
                               neg_report, neg_dxf["path"], neg_prev))

    v01recs = []
    for c in B.l1_cases():
        plan = load_plan(B.build_v01_baseline(c))
        rep = verify_plan(plan, c["gt"], level="auto")
        v01recs.append({"name": c["name"], "verdict": rep["verdict"],
                        "recall": rep["recall"]})

    by = {r["name"]: r for r in records}
    l2 = [by["L2a"], by["L2b"]]
    gates = {
        "L1_pass": all(by[n]["verdict"] == "PASS" for n in ("L1a", "L1b", "L1c")),
        "L1_no_regression": (
            sum(1 for n in ("L1a", "L1b", "L1c") if by[n]["verdict"] == "PASS")
            >= sum(1 for v in v01recs if v["verdict"] == "PASS") - 0),
        "L2_mean_recall_ge_090": sum(r["recall"] for r in l2) / len(l2) >= 0.90,
        "L2_min_recall_ge_080": min(r["recall"] for r in l2) >= 0.80,
        "L2_verdicts_pass": all(r["verdict"] == "PASS" for r in l2),
        "neg_control_fails": by["L2-neg"]["verdict"] == "FAIL",
        "neg_bbox_trap": (by["L2-neg"]["bbox_iou_advisory"] or 0) > 0.80,
        "reports_conformant": all(r["report_conformant"] for r in records),
    }
    gates["RELEASE"] = all(gates.values())

    report = {
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "env": {"python": sys.version.split()[0],
                "jev": "not wired into bench (unit-tested separately)"},
        "gates": gates,
        "v01_baseline": v01recs,
        "cases": records,
        "known_gaps": [
            "N1: manual/uncertain L1 在绝对 mm-IoU 下失败（L1a-manual IoU 0.805）。"
            "形状正确（w/h 比 2.4995 vs 2.5），只错 fallback S=3.78。"
            "spec §5 称 L1 只看归一化形状，verifier 尚无归一化分支——verifier 后续任务。",
            "N2: key_dimensions 边索引依赖 GT/plan 点序对应（同一物理边对齐）。"
            "方孔键天然稳定；外轮廓长边键已对齐并文档化，tracer 改点序会显式 FAIL。",
            "N3: verifier.infer_level 只分 L1/L2；L3a 沿用 L2 门限（IoU0.90/rib/2%）"
            "记 PASS(ref)，非冻结门限。L3rib_0 端点误差 1.008mm 距门限 1.0mm 仅差 0.008mm。",
            "N4: bench rib 须为背景孤立细条（宽≤8px）；嵌入零件内部的黑筋条"
            "与填充融合不可见（L2a 初版 10px 条亦超 rib 滤波上限，见 tests）。",
        ],
    }
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"gates": gates,
                      "L2_mean": sum(r["recall"] for r in l2) / len(l2),
                      "L3": by["L3a"]["recall_detail"]}, indent=1))
    print("RELEASE" if gates["RELEASE"] else "NO-RELEASE")
    return 0 if gates["RELEASE"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
