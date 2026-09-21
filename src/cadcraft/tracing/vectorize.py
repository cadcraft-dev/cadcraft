"""P1: raster -> vector pre-pass. lines + circles + rect fit + preview."""
from __future__ import annotations

def vectorize_raster(image_path: str, preview_path: str | None = None, debug: bool = False) -> dict:
    try:
        import cv2
        import numpy as np
    except ImportError as e:
        return {"ok": False, "error": f"opencv missing: {e}", "segments": [], "circles": []}
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return {"ok": False, "error": f"cannot read {image_path}", "segments": [], "circles": []}
    # 去噪+二值化: 高斯模糊压扫描噪，再OTSU
    blur = cv2.GaussianBlur(img, (3, 3), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(bw, 50, 150)

    lines = cv2.HoughLinesP(edges, 1, 3.14159/180, 80, minLineLength=60, maxLineGap=12)
    segs = []
    if lines is not None:
        import numpy as _np
        arr = _np.asarray(lines).reshape(-1, 4)
        for x1, y1, x2, y2 in arr[:500]:
            segs.append([int(x1), int(y1), int(x2), int(y2)])

    # 圆: 描图里孔最关键，HoughCircles补上直线检测不到的
    circles = []
    inv = 255 - bw
    found = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, 1, 100,
                             param1=150, param2=40, minRadius=20, maxRadius=200)
    if found is not None:
        for x, y, r in found[0][:20]:
            circles.append({"cx": float(x), "cy": float(y), "r": float(r)})

    # 矩形拟合: 最大外轮廓逼近，用来给LLM一个“疑似主体”
    rect_fit = None
    contours, _ = cv2.findContours(inv, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        cnt = max(contours, key=cv2.contourArea)
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        x, y, w, h = cv2.boundingRect(cnt)
        rect_fit = {"approx_points": len(approx), "bbox": [int(x), int(y), int(w), int(h)],
                    "area": float(cv2.contourArea(cnt))}

    out = {"ok": True, "segments": segs, "count": len(segs),
           "circles": circles, "rect_fit": rect_fit,
           "size": [int(img.shape[1]), int(img.shape[0])]}
    if preview_path:
        vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        for x1, y1, x2, y2 in segs[:200]:
            cv2.line(vis, (x1, y1), (x2, y2), (0, 0, 255), 1)
        for c in circles:
            cv2.circle(vis, (int(c["cx"]), int(c["cy"])), int(c["r"]), (0, 255, 0), 2)
        cv2.imwrite(preview_path, vis)
        out["preview"] = preview_path
    if debug:
        out["debug"] = {"edge_pixels": int((edges > 0).sum())}
    return out
