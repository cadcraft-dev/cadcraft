"""P1 scaffold: raster -> vector pre-pass (OpenCV/LSD + contour)."""
from __future__ import annotations
def vectorize_raster(image_path: str) -> dict:
    try:
        import cv2
    except ImportError as e:
        return {"ok": False, "error": f"opencv missing: {e}", "segments": []}
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return {"ok": False, "error": f"cannot read {image_path}", "segments": []}
    _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(bw, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, 3.14/180, 100, minLineLength=50, maxLineGap=10)
    segs = [list(map(int, l[0])) for l in (lines or [])][:500]
    return {"ok": True, "segments": segs, "count": len(segs)}
