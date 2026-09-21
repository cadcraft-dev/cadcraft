# CadCraft Product Plan (v0.1 MVP)

## Goal
Prove: 4B/2B local model + deterministic kernel + fast judge can deliver dimension-correct DXF for everyday parts, without sending drawings to the cloud by default.

## Scope (matches user sign-off)
1. 文本出DXF (P0): text -> plan JSON -> ezdxf -> verify -> repair x3. Done in v0.1.
2. Jev裁判 (P0): Score/Choice/Noul client + local fallback. Verifier uses Jev only with flag.
3. 图片描图 (P1): CV pre-pass + OCR + stitch. Scaffold in v0.1, accuracy in v0.2.
4. AutoCAD/FreeCAD联调 (P1): same plan drives pyautocad / FreeCAD headless / CadQuery.

## Metrics (borrowed from Pointer-CAD v2, simplified to 2D)
- Vertex accuracy: predicted insertion/endpoint within tol = min_bbox_edge/1000.
- Edge accuracy: endpoints + radius/center for arcs/circles within tol.
- Face/loop accuracy: closed profile + area within 0.5%.
- RMR@3 analogue: <=3 wrong entities counts as repairable. Track repair success rate.
- Cost/latency: local tokens free, Jev calls counted, p50/p95 logged in report.json.

## Milestones
- v0.1 (this scaffold): runnable text->dxf + tolerance + Jev stub + Rust geom stub.
- v0.2: tracing MVP on 10 sample drawings, block library + RAG for layer styles.
- v0.3: FreeCAD STEP export + AutoCAD live driver + LoRA dataset pipeline (指令->计划->代码三元组).
