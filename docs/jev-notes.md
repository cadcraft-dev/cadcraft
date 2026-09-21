# Jev Notes (for CadCraft)

Source: TypeSafe AI, Diogo Almeida (ex-OpenAI), System One Models & Jev, 2026-09-15. https://typesafe.ai/blog/introducing-system-one-models-and-jev

What it is: not a chat LLM; parallel sampler returning typed decisions (Noul Yes/No, Choice pick-one, Score grade) + calibrated probabilities. 70-500ms, $0.042/MTok in, out free. RLCD training. Cannot hallucinate types by design.

Why viral: agent judge (LangChain Jev-as-a-Judge 0.44s/$0.00035), 724 ads/8724 judgments in 40s for $0.09, fast-jev-compaction for Claude Code, browser-agent action selection.

How CadCraft uses it (`src/cadcraft/verifier/jev_judge.py`):
- Score: dimensional acceptance 0-100 + reason codes.
- Choice: entity class (wall/door/dim/noise) for tracing; tool relevance for compaction.
- Noul: done? needs_human? repairable?
- Fallback: if no API key, local heuristics return same schema with confidence 0.5.

Caution: cloud-only, early access, vendor benchmarks are high-end, no CAD-tolerance validation yet. Keep local verifier authoritative; Jev is advisory until we measure calibration on drawings.
