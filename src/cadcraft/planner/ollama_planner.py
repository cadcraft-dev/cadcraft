from __future__ import annotations
import json, os, urllib.request
from .schema import Plan, parse_plan, heuristic_plan_from_text

SYSTEM = ("你是CAD出图员，只输出JSON计划，不输出坐标。单位mm，参数用L1/W1/D1/R1命名，"
          "steps里op只能是rect/circle/hole_center_rect/fillet/dim。示例："
          '{"units":"mm","params":{"L1":80,"W1":50,"D1":20},"steps":[{"op":"rect","x":0,"y":0,"w":"L1","h":"W1"},{"op":"hole_center_rect","d":"D1"}]}')

def plan_from_text(text: str, model: str | None = None, timeout: int = 60) -> Plan:
    model = model or os.environ.get("CADCRAFT_MODEL", "qwen3:4b")
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    prompt = SYSTEM + f"\n需求：{text}\n只返回JSON。"
    try:
        req = urllib.request.Request(host + "/api/generate",
            data=json.dumps({"model": model, "prompt": prompt, "stream": False,
                             "format": "json", "options": {"temperature": 0.1}}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode()).get("response", "{}")
        return parse_plan(json.loads(out))
    except Exception as e:
        p = heuristic_plan_from_text(text)
        p.notes += f" [ollama fallback: {e}]"
        return p
