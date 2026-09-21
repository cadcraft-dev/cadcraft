# Tracing Benchmark (synthetic, reproducible, no copyright risk)

Internet search found open references (no images copied to avoid license issues):
- Floor-Plan-Recognition (96 stars): https://github.com/RasterScan/Floor-Plan-Recognition
- floor-plan-vectorizer: https://github.com/pimenoffd/floor-plan-vectorizer
- ABC Dataset (1M CAD): https://deep-geometry.github.io/abc-dataset/
- DeepCAD (ICCV21): https://github.com/rundiwu/DeepCAD
- CubiCasa5K / RPLAN (floor-plan datasets, for v0.2 with license check)

Local 3-level suite in `tests/testdata/` (PIL-generated, deterministic):
- L1 `synth_rect.png`: 80x50 rect + Phi20 hole. Result: PASS. 8 segs, 1 circle, OCR 80x50, DXF exact.
- L2 `level2_bracket.png`: L-bracket + 2xPhi10 + 120x20. Result: PARTIAL (60%).
  Detects 10 segs + 2 circles + OCR 2xPhi10/120x20 correct, but stitch only emits single rect+hole, drops L-shape/rib.
- L3 `level3_floor.png`: 5400x3600 walls + door gap + window. Result: FAIL-as-CAD (20%).
  Detects 15 segs, outer bbox 4pts, door gap visible in preview, but stitch only emits outer rect. Inner walls/door/window lost. Tol=3.6mm hides error (bbox huge).

Run:
```bash
PYTHONPATH=src python examples/trace_image.py --image tests/testdata/level2_bracket.png --out /tmp/l2.dxf --preview /tmp/l2.png
PYTHONPATH=src python examples/trace_image.py --image tests/testdata/level3_floor.png --out /tmp/l3.dxf --preview /tmp/l3.png
```

Next (v0.2):
1. wall-aware stitch: thick-line mask + connected components -> wall polygons, not single rect.
2. Jev Choice: classify each segment wall/door/window/noise (replaces hand thresholds).
3. text-mask split: OCR boxes removed before line detection (fixes Phi-on-circle).
4. scale solver: use longest OCR dim to solve px/mm instead of --scale guess.
