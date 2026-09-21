"""muse-spark(主脑) + Jev(裁判) 的最小配合模板。

逻辑：
  1. muse-spark 负责生成/改代码（这里用占位函数代替，你换成自己的调用）。
  2. Jev 只做判断：做完了吗？改坏了吗？下一步干嘛？全部是 state+questions。
  3. 有 TYPESAFE_API_KEY 走真 Jev；没有就抛错提醒，而不是静默用大模型瞎猜。
"""
import json
import os
import urllib.request

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

# 可调阈值：Jev 给的是校准概率，直接进 if
DONE_THRESHOLD = 0.7
NO_REGRESSION_THRESHOLD = 0.6


def jev_ask(state: str, questions: dict) -> dict:
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY 未设置：export TYPESAFE_API_KEY=... 后再跑")
    payload = {"model": MODEL, "state": state, "questions": questions}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def build_state(task: str, diff: str, test_log: str) -> str:
    # Jev 吃整段程序状态：任务 + 改动 + 测试输出全拼进去，别只给结论
    return f"TASK:\n{task}\n\nDIFF:\n{diff}\n\nTEST LOG:\n{test_log}"


CODE_JUDGE_QUESTIONS = {
    # 做完了吗？
    "done": {"type": "noul", "instructions": "The task goal is fully achieved by this diff and test log"},
    # 改坏了吗？重跑能解决吗？
    "no_regression": {
        "type": "noul",
        "instructions": "No new breakage is introduced and existing tests still pass",
    },
    # 质量打分 0/1/2
    "quality": {
        "type": "score",
        "instructions": "Code quality of this change",
        "criteria": ["needs rework", "acceptable", "clean"],
    },
    # 下一步路由：多 agent 派单就靠这个
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


def main() -> None:
    # 示例输入：你之后换成 muse-spark 真实的输出
    task = "Fix failing test in login flow, never edit src/generated."
    diff = "M src/login.ts: null-check added before token read"
    test_log = "PASS login.test.ts (3 passed)"

    state = build_state(task, diff, test_log)
    body = jev_ask(state, CODE_JUDGE_QUESTIONS)
    answers = body["answers"]

    done = answers["done"]["noul"]
    no_reg = answers["no_regression"]["noul"]
    quality = answers["quality"]["score"]
    nxt = answers["next_action"]["choice"]
    probs = answers["next_action"]["probabilities"]

    print(json.dumps(body, ensure_ascii=False, indent=2))
    print(f"\ndone={done:.2f} no_regression={no_reg:.2f} quality={quality} next={nxt} {probs}")

    if done >= DONE_THRESHOLD and no_reg >= NO_REGRESSION_THRESHOLD and nxt == "ship":
        print("→ 结论：可合入。")
    elif nxt == "fix" or done < DONE_THRESHOLD:
        print("→ 结论：打回给 muse-spark 修，再跑一轮。")
    else:
        print("→ 结论：重跑测试再判一次。")


if __name__ == "__main__":
    main()
