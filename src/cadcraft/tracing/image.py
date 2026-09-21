"""最小灰度图（纯标准库）：PGM P5 编解码 + 合成夹具绘制。

t2 的 tracing 全链路只依赖本模块的 ``GrayImage``，不依赖 numpy/PIL/OpenCV，
保证无网络环境可跑、单测可自举合成 L2 bracket 夹具。
"""

from __future__ import annotations

import math


class GrayImage:
    """8bit 灰度图，pixels[y][x]，原点左上，y 向下。"""

    def __init__(self, width: int, height: int, fill: int = 255):
        if width < 1 or height < 1:
            raise ValueError(f"illegal size {width}x{height}")
        self.width = int(width)
        self.height = int(height)
        v = max(0, min(255, int(fill)))
        self.pixels = [[v] * self.width for _ in range(self.height)]

    def get(self, x: int, y: int) -> int:
        return self.pixels[y][x]

    def set(self, x: int, y: int, v: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[y][x] = max(0, min(255, int(v)))

    def copy(self) -> "GrayImage":
        img = GrayImage(self.width, self.height)
        img.pixels = [row[:] for row in self.pixels]
        return img

    # -- 绘制（测试夹具/掩膜用） ------------------------------------------

    def fill_rect(self, x0, y0, x1, y1, v: int) -> None:
        """填充矩形，x1/y1 为开区间。"""
        v = max(0, min(255, int(v)))
        for y in range(max(0, int(y0)), min(self.height, int(y1))):
            row = self.pixels[y]
            for x in range(max(0, int(x0)), min(self.width, int(x1))):
                row[x] = v

    def fill_polygon(self, points, v: int) -> None:
        """偶奇规则扫描线填充（像素中心判定），见 geometry.scanline_fill。"""
        from .geometry import scanline_fill

        v = max(0, min(255, int(v)))
        for x, y in scanline_fill(points):
            if 0 <= x < self.width and 0 <= y < self.height:
                self.pixels[y][x] = v

    def draw_line(self, x0, y0, x1, y1, v: int, width: int = 1) -> None:
        """粗线段（点到线段距离 ≤ width/2 即涂）。"""
        v = max(0, min(255, int(v)))
        r = max(0.5, width / 2.0)
        x_lo = max(0, int(math.floor(min(x0, x1) - r)))
        x_hi = min(self.width - 1, int(math.ceil(max(x0, x1) + r)))
        y_lo = max(0, int(math.floor(min(y0, y1) - r)))
        y_hi = min(self.height - 1, int(math.ceil(max(y0, y1) + r)))
        dx, dy = x1 - x0, y1 - y0
        denom = dx * dx + dy * dy
        for y in range(y_lo, y_hi + 1):
            for x in range(x_lo, x_hi + 1):
                px, py = x + 0.5, y + 0.5
                if denom == 0:
                    d = math.hypot(px - x0, py - y0)
                else:
                    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / denom))
                    d = math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))
                if d <= r:
                    self.pixels[y][x] = v

    # -- 二值化 / 背景 -----------------------------------------------------

    def threshold(self, level: int = 128) -> list:
        """暗部为前景 1（线条图：黑线白底），返回 h×w 的 0/1 表。"""
        return [[1 if p < level else 0 for p in row] for row in self.pixels]

    def background(self) -> int:
        """四角众数作为底色（白底图 255 / 蓝晒图底色）。"""
        corners = [
            self.pixels[0][0],
            self.pixels[0][self.width - 1],
            self.pixels[self.height - 1][0],
            self.pixels[self.height - 1][self.width - 1],
        ]
        return max(set(corners), key=corners.count)

    # -- PGM P5 ------------------------------------------------------------

    def to_pgm(self) -> bytes:
        header = f"P5\n{self.width} {self.height}\n255\n".encode("ascii")
        body = b"".join(bytes(row) for row in self.pixels)
        return header + body

    @staticmethod
    def from_pgm(data: bytes) -> "GrayImage":
        tokens, pos = [], 0
        magic = data[pos : pos + 2]
        if magic != b"P5":
            raise ValueError(f"only P5 supported, got {magic!r}")
        pos = 2
        while len(tokens) < 3:
            while pos < len(data) and chr(data[pos]).isspace():
                pos += 1
            if data[pos : pos + 1] == b"#":
                while pos < len(data) and data[pos : pos + 1] != b"\n":
                    pos += 1
                continue
            start = pos
            while pos < len(data) and not chr(data[pos]).isspace():
                pos += 1
            tokens.append(data[start:pos].decode("ascii"))
        w, h, maxv = int(tokens[0]), int(tokens[1]), int(tokens[2])
        if maxv != 255:
            raise ValueError(f"maxv must be 255, got {maxv}")
        pos += 1  # 单个空白分隔符
        raw = data[pos : pos + w * h]
        if len(raw) < w * h:
            raise ValueError("truncated PGM body")
        img = GrayImage(w, h)
        for y in range(h):
            img.pixels[y] = list(raw[y * w : (y + 1) * w])
        return img
