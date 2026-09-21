# Architecture: Plan-Then-Construct + Verify

```
User text / image
  -> Planner (System 2, Ollama Qwen3-4B, JSON-only, temp 0.1)
     plan: {units, params{L1..}, steps[], constraints[]}
  -> Executor (deterministic Python/Rust, no LLM math)
     ezdxf / FreeCAD / AutoCAD drivers compute coordinates exactly
  -> Verifier (System 1 + math)
     a) local tolerance.py: bbox/1000 checks, closed-loop, area
     b) jev_judge.py (optional): Score acceptance, Choice classification, Noul done?
  -> Repair (max 3): feed error JSON back to planner, regen plan only
  -> DXF + preview PNG + report.json
```

Invariants:
- LLM never emits raw coordinates; it emits symbols + refs (L3=2*L2). Executor resolves.
- All lengths carry units; unified to mm before execution (like OmniCAD-Plan dict).
- Every executor output must pass verifier; failures return structured errors, not prose.
- Jev is a judge, never a generator. Cloud only with explicit flag.
