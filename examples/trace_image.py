"""Example (P1): raster -> segments + OCR -> Plan -> DXF."""
import argparse, json
from cadcraft.tracing import vectorize_raster, read_dimensions, stitch_to_plan
from cadcraft.executor import execute_plan_to_dxf
from cadcraft.verifier import verify
ap = argparse.ArgumentParser()
ap.add_argument("--image", required=True)
ap.add_argument("--out", default="/tmp/traced.dxf")
ap.add_argument("--preview", default="/tmp/traced_preview.png")
ap.add_argument("--scale", type=float, default=5.0, help="px per mm when OCR has no dims")
a = ap.parse_args()
vec = vectorize_raster(a.image, preview_path=a.preview, debug=True)
ocr = read_dimensions(a.image)
plan = stitch_to_plan(vec, ocr.get("texts", []), scale_px_per_mm=a.scale)
exec_info = execute_plan_to_dxf(plan, a.out)
tol = verify(exec_info, plan)
print(json.dumps({"vec_count": vec.get("count"), "circles": vec.get("circles"),
                  "rect_fit": vec.get("rect_fit"), "ocr": ocr.get("texts"),
                  "plan_notes": plan.notes, "tol": tol, "dxf": a.out,
                  "preview": a.preview}, ensure_ascii=False, indent=2))
