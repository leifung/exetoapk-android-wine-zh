#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯标准库生成暗黑风格启动图标（无需 Pillow），输出多密度 PNG。"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "icons"
SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def render(size: int, transparent: bool = False) -> bytes:
    c = (size - 1) / 2.0
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            dx, dy = (x - c) / c, (y - c) / c
            r = math.hypot(dx, dy)
            d = abs(dx) + abs(dy)
            a = 255
            if transparent:
                # 自适应图标前景：外围留白，内容缩到 62%
                R = G = B = 0
                if r < 0.72:
                    a = 255
                else:
                    a = 0
            else:
                bg = int(20 * (1 - min(r, 1.0)))
                R, G, B = bg + 8, bg + 2, max(0, bg - 3)
                if 0.84 < r < 0.92:
                    R, G, B = 168, 126, 52
            if r < 0.76:
                if d < 0.62:
                    t = d / 0.62
                    R = int(214 - 132 * t)
                    G = int(30 + 12 * t)
                    B = int(18 + 8 * t)
                    if d < 0.32:
                        R = min(255, R + 46)
                        G = min(255, G + 20)
                if d < 0.17:
                    R, G, B = 226, 184, 88
                elif d < 0.22:
                    R, G, B = 96, 62, 24
            row += bytes((max(0, min(255, R)), max(0, min(255, G)), max(0, min(255, B)), a))
        rows.append(b"\x00" + bytes(row))
    raw = b"".join(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for density, size in SIZES.items():
        (OUT / f"ic_launcher_{density}.png").write_bytes(render(size))
        (OUT / f"ic_launcher_round_{density}.png").write_bytes(render(size))
        (OUT / f"ic_launcher_foreground_{density}.png").write_bytes(render(size, transparent=True))
    (OUT / "ic_launcher_512.png").write_bytes(render(512))
    print(f"[OK] 生成 {len(SIZES)*3+1} 个图标 -> {OUT}")


if __name__ == "__main__":
    main()
