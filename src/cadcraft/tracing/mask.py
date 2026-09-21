"""Text-mask（spec §6）：OCR → 掩膜 → 几何检测，顺序铁律。

- 只盖文字 bbox（外扩 pad），不盖标注引线；
- 填充底色（四角众数：白底 255 / 蓝晒按底色），防掩膜块自身变成新轮廓；
- 返回实际涂抹的整数框，供 pipeline 审计（debug.masked_boxes）。
"""

from __future__ import annotations


def normalize_box(bbox, width: int, height: int, pad: int = 0):
    """float bbox → 裁剪到图内的整数 [x0,y0,x1,y1]（x1/y1 开区间）；非法返回 None。"""
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None
    x0 = max(0, int(min(x0, x1)) - pad)
    y0 = max(0, int(min(y0, y1)) - pad)
    x1 = min(width, int(max(float(bbox[0]), float(bbox[2]))) + pad + 1)
    y1 = min(height, int(max(float(bbox[1]), float(bbox[3]))) + pad + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1, y1]


def mask_text_boxes(image, boxes, pad: int = 3, fill=None):
    """在拷贝图上涂掉文字区。

    :param image: GrayImage。
    :param boxes: bbox 列表（float 允许，bbox_px 语义）。
    :param pad: 外扩像素（spec §6：2–3px，默认 3）。
    :param fill: 填充色，None 则取 image.background()。
    :return: (masked_image, painted_boxes)。
    """
    out = image.copy()
    bg = image.background() if fill is None else max(0, min(255, int(fill)))
    painted = []
    for b in boxes or []:
        nb = normalize_box(b, image.width, image.height, pad)
        if nb is None:
            continue
        x0, y0, x1, y1 = nb
        out.fill_rect(x0, y0, x1, y1, bg)
        painted.append(nb)
    return out, painted
