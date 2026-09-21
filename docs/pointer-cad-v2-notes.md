# Pointer-CAD v2 Notes (for CadCraft)

Source: Qi et al., HKU, ECCV 2026, arXiv:2606.29301. Repo https://github.com/Snitro/Pointer-CAD-v2 (code coming soon at time of writing).

Takeaways ported into CadCraft:
1. Last-millimeter problem: quantization (0.7 -> 0.67) + normalized CD/IoU hides errors. -> We evaluate unnormalized, tol=bbox_min/1000.
2. Plan-Then-Construct: text-domain plan with <L>/<A> + units + arithmetic/refs, then param dict (length/angle split, mm-normalized, sign-preserving log norm, Fourier, RoPE) + pointer retrieval via cosine. -> We mimic with JSON plan + Python resolver (no learned pointer in v0.1).
3. Three heads: Label/Value/Pointer. -> We mimic with planner/executor/judge process split.
4. Data: OmniCAD-Plan 202K / Plan+ 209K via Qwen3 annotation + checks. -> Our LoRA set should be 指令->计划->代码 triples, same shape.
5. Results: 1.5B beats CADmium-1.5B +13.49%, arc 5.61%->68.53%, beats Gemini 3 Pro ~21.3%, CD 0.91 vs GPT-5.2 12.01, 7B RMR@3 95.23%. Ablation: w/o Ref -26.54%, w/o Plan -12.96%.
6. Limits: small holes/slender cylinders fail, plan error propagates. -> Our repair loop + human-in-loop for <1mm features.
