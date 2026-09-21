from __future__ import annotations
import json, os, urllib.request
from dataclasses import dataclass

@dataclass
class JevResult:
    kind: str  # Score | Choice | Noul
    value: object
    confidence: float
    raw: dict

def _fallback(question: str, exec_info: dict, tol_report: dict) -> JevResult:
    # local heuristic with same schema when no API key
    score = 95.0 if tol_report.get("passed") else (60.0 if tol_report.get("rmr3_repairable") else 20.0)
    return JevResult(kind="Score", value={"accept": score, "question": question},
                     confidence=0.5, raw={"fallback": True, "tol": tol_report})

def jev_score(question: str, exec_info: dict, tol_report: dict, timeout: int = 10) -> JevResult:
    """Ask Jev Score: is this drawing dimensionally acceptable? Cloud only with key."""
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key:
        return _fallback(question, exec_info, tol_report)
    # Minimal TypeSafe-style call; endpoint/shape may evolve in early access — keep isolated here.
    body = {"state": json.dumps({"question": question, "entities": exec_info.get("entities", []),
                                 "bbox_mm": exec_info.get("bbox_mm"), "tol": tol_report}, ensure_ascii=False),
            "questions": {"accept": {"type": "score", "criteria": question}}}
    try:
        req = urllib.request.Request("https://api.typesafe.ai/v1/decide",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = json.loads(r.read().decode())
        # normalize vendor shape defensively
        val = raw.get("accept", raw)
        conf = float(raw.get("confidence", 0.7)) if isinstance(raw, dict) else 0.7
        return JevResult(kind="Score", value=val, confidence=conf, raw=raw)
    except Exception as e:
        fb = _fallback(question, exec_info, tol_report)
        fb.raw["jev_error"] = str(e)
        return fb
