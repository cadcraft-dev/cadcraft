from __future__ import annotations
import json
from .planner import plan_from_text
from .planner.schema import plan_to_json
from .executor import execute_plan_to_dxf
from .verifier import verify, jev_score

def run_text_to_dxf(text: str, out_path: str, with_jev: bool = False, max_repair: int = 3) -> dict:
    plan = plan_from_text(text)
    attempt, history = 0, []
    while True:
        exec_info = execute_plan_to_dxf(plan, out_path)
        tol = verify(exec_info, plan)
        jev = jev_score("尺寸是否合格、可否交付？", exec_info, tol).value if with_jev else None
        # Jev advisory: only fail when local fails (keep local authoritative in v0.1)
        passed = tol["passed"]
        history.append({"attempt": attempt, "plan": json.loads(plan_to_json(plan)),
                        "exec": exec_info, "tol": tol, "jev": jev})
        if passed or attempt >= max_repair:
            break
        attempt += 1
        # repair: re-plan with error context appended (plan-only regen)
        err = "; ".join(c["name"] + ": " + c["detail"] for c in tol["checks"] if not c["passed"])
        plan = plan_from_text(text + f" [上轮不合格:{err}，请修正参数和步骤]")
    report = {"ok": history[-1]["tol"]["passed"], "attempts": len(history),
              "dxf": out_path, "history": history}
    with open("report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report
