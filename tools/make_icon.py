"""Generate dashboard/assets/icon.png and icon.ico (pure Python, no Pillow). Run: python tools/make_icon.py"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "dashboard" / "assets"


def render(size: int) -> bytes:
    """Rounded dark tile with an electric-blue pulse line, 4x supersampled."""
    ss = 4
    n = size * ss
    bg, edge, blue = (13, 17, 23), (33, 41, 54), (56, 139, 253)
    px = bytearray(n * n * 4)
    r = n * 0.22

    def inside(x: float, y: float) -> bool:
        cx = min(max(x, r), n - r)
        cy = min(max(y, r), n - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    pts = [(0.10, 0.52), (0.30, 0.52), (0.38, 0.30), (0.50, 0.76), (0.60, 0.40), (0.66, 0.52), (0.90, 0.52)]
    segs = [((a[0] * n, a[1] * n), (b[0] * n, b[1] * n)) for a, b in zip(pts, pts[1:])]
    w = n * 0.055

    def dist(px_, py_, s):
        (x1, y1), (x2, y2) = s
        dx, dy = x2 - x1, y2 - y1
        t = max(0, min(1, ((px_ - x1) * dx + (py_ - y1) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px_ - (x1 + t * dx), py_ - (y1 + t * dy))

    for y in range(n):
        for x in range(n):
            i = (y * n + x) * 4
            if not inside(x + 0.5, y + 0.5):
                continue
            col = bg
            border = min(x, y, n - 1 - x, n - 1 - y)
            if border < n * 0.012 or not inside(x + 0.5 + (1 if x < n / 2 else -1) * n * 0.012, y + 0.5 + (1 if y < n / 2 else -1) * n * 0.012):
                col = edge
            if min(dist(x + 0.5, y + 0.5, s) for s in segs) <= w:
                col = blue
            px[i:i + 4] = bytes((*col, 255))
    out = bytearray()
    for y in range(size):
        row = bytearray()
        for x in range(size):
            acc = [0, 0, 0, 0]
            for dy in range(ss):
                for dx in range(ss):
                    j = ((y * ss + dy) * n + x * ss + dx) * 4
                    a = px[j + 3]
                    acc[0] += px[j] * a
                    acc[1] += px[j + 1] * a
                    acc[2] += px[j + 2] * a
                    acc[3] += a
            if acc[3]:
                row += bytes((acc[0] // acc[3], acc[1] // acc[3], acc[2] // acc[3], acc[3] // (ss * ss)))
            else:
                row += b"\0\0\0\0"
        out += b"\0" + row
    return png(size, size, bytes(out))


def png(w: int, h: int, raw: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(images: list[tuple[int, bytes]]) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return head + entries + blobs


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 48, 64, 128, 256]
    imgs = [(s, render(s)) for s in sizes]
    (OUT / "icon.png").write_bytes(dict(imgs)[256])
    (OUT / "icon.ico").write_bytes(ico(imgs))
    print("wrote", OUT / "icon.png", OUT / "icon.ico")
