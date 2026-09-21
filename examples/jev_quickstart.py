"""Jev 最小验证：只确认你的 TYPESAFE_API_KEY 能通，不碰业务逻辑。"""
import os
import sys
import json
import urllib.request

API_URL = "https://api.typesafe.ai/v1/systemone"

def main() -> int:
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        print("TYPESAFE_API_KEY 未设置。先执行：")
        print('  export TYPESAFE_API_KEY="你的key"')
        return 1

    payload = {
        "model": "jev-latest",
        "state": "Hi, I've been trying to connect my Stripe account for 3 days and the integration keeps failing. I'm losing sales. Please help ASAP.",
        "questions": {
            "is_urgent": {"type": "noul", "instructions": "The message conveys urgency or time-sensitivity"},
            "department": {
                "type": "choice",
                "instructions": "Which team should handle this",
                "criteria": {
                    "billing": "Payment or subscription issues",
                    "technical": "Bugs or integration problems",
                    "sales": "Pricing or account questions",
                },
            },
        },
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001 - 直接把服务端回执打出来方便排错
        print(f"调用失败：{e}")
        return 1

    print(json.dumps(body, ensure_ascii=False, indent=2))
    print("\nOK：能看到 answers.is_urgent.noul 和 answers.department.choice 就算通了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
