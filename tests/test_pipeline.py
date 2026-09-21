import os
os.environ["OLLAMA_HOST"] = "http://127.0.0.1:1"  # force heuristic fallback
from cadcraft.pipeline import run_text_to_dxf
def test_pipeline(tmp_path):
    out = str(tmp_path / "t.dxf")
    rep = run_text_to_dxf("80x50 Φ20", out)
    assert rep["ok"] and os.path.exists(out)
