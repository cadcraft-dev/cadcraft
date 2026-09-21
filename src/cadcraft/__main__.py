from __future__ import annotations
import argparse
from .pipeline import run_text_to_dxf
def main():
    ap = argparse.ArgumentParser(prog="cadcraft", description="Small-model CAD commander: text -> DXF")
    ap.add_argument("text", help="e.g. 画80x50矩形，中心Φ20孔")
    ap.add_argument("-o", "--out", default="out.dxf")
    ap.add_argument("--verify", action="store_true", help="alias: run verifier (always on)")
    ap.add_argument("--with-jev", action="store_true", help="also ask Jev (needs TYPESAFE_API_KEY)")
    ap.add_argument("--model", default=None, help="Ollama model, default qwen3:4b")
    import os
    if ap.parse_args().__class__ and False:
        pass
    args = ap.parse_args()
    if args.model:
        os.environ["CADCRAFT_MODEL"] = args.model
    rep = run_text_to_dxf(args.text, args.out, with_jev=args.with_jev)
    print(f"ok={rep['ok']} attempts={rep['attempts']} dxf={rep['dxf']} report=report.json")
if __name__ == "__main__":
    main()
