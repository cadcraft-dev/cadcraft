from cadcraft.tracing import vectorize_raster, read_dimensions, stitch_to_plan
def test_vectorize_synth():
    vec = vectorize_raster("tests/testdata/synth_rect.png")
    assert vec["ok"] and vec["count"] >= 4
    assert len(vec["circles"]) >= 1
    assert vec["rect_fit"]["approx_points"] == 4
def test_stitch_with_ocr():
    vec = vectorize_raster("tests/testdata/synth_rect.png")
    plan = stitch_to_plan(vec, ["80x50", "Phi20"], scale_px_per_mm=7.5)
    assert plan.params["L1"].value == 80 and plan.params["W1"].value == 50
    assert plan.params["D1"].value == 20
def test_stitch_fallback_no_zero():
    # OCR误识 0x50 不能污染计划
    vec = vectorize_raster("tests/testdata/synth_rect.png")
    plan = stitch_to_plan(vec, ["0x50"], scale_px_per_mm=7.5)
    assert plan.params["L1"].value > 0.5
