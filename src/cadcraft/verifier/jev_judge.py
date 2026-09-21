"""Jev Choice 分类器（t4）：给每段几何分类 墙/门窗/噪点。

契约：有 ``TYPESAFE_API_KEY`` 走云端 Jev ``choice``（wall/opening/noise 三选一，
返回校准概率）；无 key 用本地启发式，**与云端返回同一 schema**，verifier 不分支
（spec §5 末条：有/无 key 同键）。

单段输出 schema（云/本地键齐全）：::

    {
      "segment_id": "seg_0",
      "label": "wall | opening | noise",
      "confidence": 0.0,                       # 所选 label 的概率
      "probabilities": {"wall": .., "opening": .., "noise": ..},  # 和为 1
      "source": "jev-cloud | heuristic-local",
    }

顶层返回 ``{"results": [...], "source": ..., "model": ...,
"cloud_error": str | None}``。

本模块除标准库外无依赖（urllib 直调
``https://api.typesafe.ai/v1/systemone``，见 examples/jev_quickstart.py）。
"""

from __future__ import annotations

import json
import os
import urllib.request

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

LABELS = ("wall", "opening", "noise")

# 本地启发式阈值（像素域，可按图分辨率调参；云端走 Jev 不用这组值）。
WALL_MIN_LENGTH_PX = 60.0    # 足够长的段才可能是墙
WALL_MIN_WIDTH_PX = 6.0      # 足够粗的段才可能是墙
OPENING_MIN_LENGTH_PX = 30.0  # 门窗段：细但有一定长度
NOISE_MAX_LENGTH_PX = 8.0    # 极短碎段直接判噪点

_HEURISTIC_QUESTIONS = {
    "label": {
        "type": "choice",
        "instructions": (
            "Classify this CAD plan segment by its geometry: "
            "a wall is a long thick load-bearing line; "
            "an opening is a thinner medium-length door/window span, often in a wall gap; "
            "noise is a tiny fragment, speck, or text stroke remnant"
        ),
        "criteria": {
            "wall": "Long thick wall line",
            "opening": "Door or window span, thinner than a wall",
            "noise": "Tiny fragment, speck, or non-geometry remnant",
        },
    }
}


def _segment_state_text(seg: dict, index: int) -> str:
    """把一段几何转成 Jev 可读的状态行（缺失字段如实写 unknown，不编造）。"""
    seg_id = seg.get("id", f"seg_{index}")
    length = seg.get("length_px", "unknown")
    width = seg.get("width_px", "unknown")
    touches = seg.get("touches_wall", "unknown")
    extra = seg.get("note", "")
    line = (
        f"segment {seg_id}: length_px={length}, width_px={width}, "
        f"touches_wall={touches}"
    )
    if extra:
        line += f", note={extra}"
    return line


def build_choice_questions(segments: list[dict]) -> tuple[str, dict]:
    """为一批段构造 (state, questions)：每段一道 choice 三选题。"""
    lines = [
        "Classify each CAD floor-plan segment as wall, opening (door/window), or noise.",
        "Use only the geometry given per segment; missing values are written as unknown.",
    ]
    questions: dict = {}
    for i, seg in enumerate(segments):
        seg_id = str(seg.get("id", f"seg_{i}"))
        lines.append(_segment_state_text(seg, i))
        questions[f"seg_{i}__{seg_id}"] = {
            "type": "choice",
            "instructions": _HEURISTIC_QUESTIONS["label"]["instructions"],
            "criteria": dict(_HEURISTIC_QUESTIONS["label"]["criteria"]),
        }
    return "\n".join(lines), questions


def jev_ask(state: str, questions: dict, api_key: str, timeout: int = 30) -> dict:
    """直调 Jev SystemOne，返回原始 answers body。"""
    payload = {"model": MODEL, "state": state, "questions": questions}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _norm_probs(probs: dict) -> dict:
    """把概率归一化到 LABELS 三键、和为 1（缺键补 0）。"""
    vals = {k: float(probs.get(k, 0.0) or 0.0) for k in LABELS}
    total = sum(vals.values())
    if total <= 0:
        return {k: 1.0 / len(LABELS) for k in LABELS}
    return {k: v / total for k, v in vals.items()}


def heuristic_classify(seg: dict, index: int = 0) -> dict:
    """本地启发式：无 key 时的同 schema 降级（规则见模块阈值常量）。

    - 极短碎段（length < NOISE_MAX_LENGTH_PX）→ noise；
    - 长且粗（≥WALL_MIN_LENGTH/width）→ wall；
    - 细但有长度（≥OPENING_MIN_LENGTH_PX）→ opening；
    - 其余（无尺寸信息/过细过短）→ noise 低置信度。
    """
    seg_id = str(seg.get("id", f"seg_{index}"))
    try:
        length = float(seg.get("length_px")) if seg.get("length_px") is not None else None
    except (TypeError, ValueError):
        length = None
    try:
        width = float(seg.get("width_px")) if seg.get("width_px") is not None else None
    except (TypeError, ValueError):
        width = None

    if length is not None and length < NOISE_MAX_LENGTH_PX:
        label, conf = "noise", 0.70
    elif (
        length is not None
        and width is not None
        and length >= WALL_MIN_LENGTH_PX
        and width >= WALL_MIN_WIDTH_PX
    ):
        label, conf = "wall", 0.80
    elif length is not None and length >= OPENING_MIN_LENGTH_PX and (
        width is None or width < WALL_MIN_WIDTH_PX
    ):
        conf = 0.65 if seg.get("touches_wall") else 0.55
        label = "opening"
    elif length is None and width is None:
        label, conf = "noise", 0.40
    else:
        label, conf = "noise", 0.60

    rest = (1.0 - conf) / 2
    probs = {k: (conf if k == label else rest) for k in LABELS}
    return {
        "segment_id": seg_id,
        "label": label,
        "confidence": conf,
        "probabilities": probs,
        "source": "heuristic-local",
    }


def _from_cloud_answers(segments: list[dict], answers: dict) -> list[dict]:
    """把 Jev answers 转成标准结果 schema（单题缺失/非法时回落该段启发式）。"""
    results = []
    for i, seg in enumerate(segments):
        seg_id = str(seg.get("id", f"seg_{i}"))
        ans = answers.get(f"seg_{i}__{seg_id}")
        try:
            label = ans["choice"]
            probs = _norm_probs(ans.get("probabilities", {}))
            if label not in LABELS:
                raise KeyError(f"unknown label {label!r}")
            results.append(
                {
                    "segment_id": seg_id,
                    "label": label,
                    "confidence": probs[label],
                    "probabilities": probs,
                    "source": "jev-cloud",
                }
            )
        except (TypeError, KeyError, AttributeError):
            item = heuristic_classify(seg, i)
            results.append(item)
    return results


def classify_segments(
    segments: list[dict],
    api_key: str | None = None,
    timeout: int = 30,
    force_local: bool = False,
) -> dict:
    """分类入口：有 key 走云，无 key（或 force_local）走本地启发式，同 schema 返回。

    云端失败（网络/鉴权/畸形回包）时降级为本地启发式，并在顶层
    ``cloud_error`` 如实记录（不静默吞错，不编造云标签）。
    """
    segments = list(segments or [])
    key = (api_key if api_key is not None else os.environ.get("TYPESAFE_API_KEY", "")).strip()

    if not key or force_local:
        return {
            "results": [heuristic_classify(s, i) for i, s in enumerate(segments)],
            "source": "heuristic-local",
            "model": None,
            "cloud_error": None,
        }

    state, questions = build_choice_questions(segments)
    try:
        body = jev_ask(state, questions, key, timeout=timeout)
        answers = body.get("answers", {})
        if not isinstance(answers, dict) or not answers:
            raise ValueError("Jev 返回缺少 answers")
    except Exception as e:  # noqa: BLE001 — 降级路径必须兜住所有云端故障
        return {
            "results": [heuristic_classify(s, i) for i, s in enumerate(segments)],
            "source": "heuristic-local",
            "model": None,
            "cloud_error": f"{type(e).__name__}: {e}",
        }
    return {
        "results": _from_cloud_answers(segments, answers),
        "source": "jev-cloud",
        "model": MODEL,
        "cloud_error": None,
    }

# ---- v0.1 Score judge (kept for pipeline --with-jev) ----
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
