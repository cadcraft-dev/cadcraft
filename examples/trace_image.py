"""Example (P1 scaffold): raster -> segments + OCR texts."""
import argparse, json
from cadcraft.tracing import vectorize_raster, read_dimensions
ap = argparse.ArgumentParser()
ap.add_argument("--image", required=True)
a = ap.parse_args()
print(json.dumps({"vec": vectorize_raster(a.image), "ocr": read_dimensions(a.image)}, ensure_ascii=False, indent=2)[:4000])
