"""P1: OCR dimension strings like 80, Phi20, R5 (with pre-process)."""
from __future__ import annotations
import re

def read_dimensions(image_path: str) -> dict:
    try:
        import cv2
        from PIL import Image
        import pytesseract
    except Exception as e:
        return {"ok": False, "error": str(e), "texts": []}
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return {"ok": False, "error": f"cannot read {image_path}", "texts": []}
    # 放大2倍+自适应二值化，工程图小字才稳
    h, w = img.shape
    big = cv2.resize(img, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cfgs = ["--psm 6 -c tessedit_char_whitelist=0123456789xXPhiR.-+ ",
            "--psm 6"]
    seen: list[str] = []
    for cfg in cfgs:
        try:
            txt = pytesseract.image_to_string(Image.fromarray(bw), config=cfg)
        except Exception:
            continue
        for line in txt.splitlines():
            s = line.strip().replace("‘", "").replace("'", "")
            # 归一化常见误识: 0x->8x? 不自动改，只收录含数字的行
            if re.search(r"\d", s) and s not in seen:
                seen.append(s)
        if seen:
            break
    # 提纯: 只留像尺寸的行
    keep = [s for s in seen if re.search(r"\d\s*[x×]\s*\d|Phi|Φ|φ|R\s*\d|\d{2,}", s, re.I) or re.search(r"\d", s)]
    return {"ok": True, "texts": keep[:20], "raw_count": len(seen)}
