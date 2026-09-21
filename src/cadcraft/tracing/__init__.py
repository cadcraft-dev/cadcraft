"""tracing: v0.2 pipeline (trace_drawing) + v0.1 compat (vectorize/OCR/stitch_to_plan)."""
from .pipeline import DEFAULT_PARAMS, null_ocr, trace_drawing
from .plan import PlanBuilder, PlanError, v01_upgrade
from .scale_solver import (parse_dimension_text, px_to_mm, solve_scale,
                           verify_anchor_consistency)
from .vectorize import vectorize_raster
from .ocr_dimensions import read_dimensions
from .stitch import (bridge_gaps, stitch_rects, stitch_to_plan, union_outlines)

__all__ = [
    "DEFAULT_PARAMS", "null_ocr", "trace_drawing",
    "PlanBuilder", "PlanError", "v01_upgrade",
    "parse_dimension_text", "px_to_mm", "solve_scale",
    "verify_anchor_consistency",
    "vectorize_raster", "read_dimensions",
    "bridge_gaps", "stitch_rects", "stitch_to_plan", "union_outlines",
]
