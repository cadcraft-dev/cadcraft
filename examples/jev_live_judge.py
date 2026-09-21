"""真机实测：对真实仓库的 diff + 真实测试输出做 Jev 验收。

用法：
  python3 examples/jev_live_judge.py --repo . --task "修好登录失败，勿动src/generated" --test "python3 -m pytest -q 2>&1 | head -n 100"

干的事：
  1. 在 --repo 里跑 `git diff --stat` + `git diff` 取真实改动（超长截断）。
  2. 跑 --test 命令取真实测试 log（超长截断，只留头尾）。
  3. 拼成 state，调 Jev 那 4 道题，和 jev_code_judge.py 同一套阈值。
  4. 输出 ship / fix / retest，给 muse-spark 当下一步指令。
"""
import argparse
import json
import os
import subprocess
import urllib.request

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
DONE_THRESHOLD = 0.7
NO_REGRESSION_THRESHOLD = 0.6

# 状态预算：Jev 请求上限 32k，这里留足余量给 questions
MAX_DIFF_CHARS = 12000
MAX_LOG_CHARS = 8000


def run(cmd: str, cwd: str) -> str:
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=120)
    out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr else "")
    return out.strip() or "(empty output)"


def truncate_middle(s: str, budget: int) -> str:
    if len(s) <= budget:
        return s
    head = budget * 2 // 3
    tail = budget - head - 60
    return s[:head] + f"\n[…截掉 {len(s) - budget} 字…]\n" + s[-tail:]


def jev_ask(state: str, questions: dict) -> dict:
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY 未设置")
    payload = {"model": MODEL, "state": state, "questions": questions}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


QUESTIONS = {
    "done": {"type": "noul", "instructions": "The task goal is fully achieved by this diff and test log"},
    "no_regression": {
        "type": "noul",
        "instructions": "No new breakage is introduced and existing tests still pass",
    },
    "quality": {
        "type": "score",
        "instructions": "Code quality of this change",
        "criteria": ["needs rework", "acceptable", "clean"],
    },
    "next_action": {
        "type": "choice",
        "instructions": "What should happen next",
        "criteria": {
            "ship": "Done and safe to merge",
            "fix": "Needs code fix then re-test",
            "retest": "Code looks fine but tests need re-running",
        },
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="真实仓库路径")
    ap.add_argument("--task", required=True, help="任务目标，一句话")
    ap.add_argument("--test", default="", help="测试命令，如 pytest / npm test")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    diff_stat = run("git diff --stat", repo)
    diff = run("git diff", repo)
    # 未提交 + 已暂存都看看，避免空 diff 误判
    if len(diff.strip()) < 10:
        diff = run("git diff HEAD --stat; echo '---'; git diff HEAD | head -n 400", repo)

    test_log = run(args.test, repo) if args.test else "(no test command given)"
    diff_t = truncate_middle(diff, MAX_DIFF_CHARS)
    log_t = truncate_middle(test_log, MAX_LOG_CHARS)

    state = f"TASK:\n{args.task}\n\nDIFF STAT:\n{diff_stat}\n\nDIFF:\n{diff_t}\n\nTEST LOG:\n{log_t}"
    print(f"repo={repo} state_chars={len(state)} diff_chars={len(diff)} log_chars={len(test_log)}")

    body = jev_ask(state, QUESTIONS)
    a = body["answers"]
    done, no_reg = a["done"]["noul"], a["no_regression"]["noul"]
    nxt, probs = a["next_action"]["choice"], a["next_action"]["probabilities"]
    print(json.dumps(body, ensure_ascii=False, indent=2))
    print(f"\ndone={done:.2f} no_regression={no_reg:.2f} next={nxt} {probs}")

    if done >= DONE_THRESHOLD and no_reg >= NO_REGRESSION_THRESHOLD and nxt == "ship":
        print("→ 给 muse-spark：可合入。")
    elif nxt == "fix" or done < DONE_THRESHOLD:
        print("→ 给 muse-spark：按 Jev 概率打回重修，重点看 diff 未覆盖处。")
    else:
        print("→ 给 muse-spark：重跑测试再判。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
