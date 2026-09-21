"""P1 scaffold: OCR dimension strings like 80, Φ20, R5."""
from __future__ import annotations
def read_dimensions(image_path: str) -> dict:
    try:
        from PIL import Image
        import pytesseract
        txt = pytesseract.image_to_string(Image.open(image_path))
    except Exception as e:
        return {"ok": False, "error": str(e), "texts": []}
    import re
    texts = [t.strip() for t in txt.splitlines() if re.search(r"\d", t)]
    return {"ok": True, "texts": texts[:50]}
