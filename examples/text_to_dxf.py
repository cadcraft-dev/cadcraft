"""Example: text -> DXF."""
import argparse
from cadcraft.pipeline import run_text_to_dxf
ap = argparse.ArgumentParser()
ap.add_argument("--text", default="画80x50矩形，中心Φ20孔")
ap.add_argument("--out", default="/tmp/demo.dxf")
ap.add_argument("--with-jev", action="store_true")
a = ap.parse_args()
rep = run_text_to_dxf(a.text, a.out, with_jev=a.with_jev)
print(f"ok={rep['ok']} attempts={rep['attempts']} -> {a.out}")
