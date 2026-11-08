#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""并发 Range 分片下载（GitHub release 单连接限速时使用），支持断点续传。"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DEFAULT_URL = "https://api.github.com/repos/brunodev85/winlator/releases/assets/563515546"
DEFAULT_SIZE = 157646000  # 由调用方用 --size 精确指定


def get_size(url: str) -> int:
    out = subprocess.run(
        ["curl", "-sS", "-L", "-I", "--max-time", "30", "-H", "Accept: application/octet-stream", url],
        capture_output=True, text=True,
    ).stdout
    for line in out.splitlines():
        if line.lower().startswith("content-length:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError("无法确定文件大小:\n" + out[-1000:])


def fetch(url: str, start: int, end: int, part: Path, idx: int) -> tuple[int, int]:
    expected = end - start + 1
    # 断点续传：已完成且大小正确的分片直接跳过
    if part.exists() and part.stat().st_size == expected:
        return idx, expected
    # 直接覆盖写目标分片，不做任何删除操作（沙箱对批量删除有限制）
    for attempt in range(5):
        r = subprocess.run(
            ["curl", "-sS", "-L", "--retry", "2", "--max-time", "420",
             "-H", "Accept: application/octet-stream",
             "-r", f"{start}-{end}", "-o", str(part), url],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and part.exists() and part.stat().st_size == expected:
            return idx, expected
        time.sleep(2 + attempt * 2)
    raise RuntimeError(f"分片 {idx} 下载失败: {r.stderr[-300:]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--size", type=int, default=0)
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--chunk-mb", type=int, default=2)
    args = ap.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = out.parent / (out.name + ".parts")
    parts_dir.mkdir(exist_ok=True)

    size = args.size or get_size(args.url)
    chunk = args.chunk_mb * 1024 * 1024
    ranges = [(s, min(s + chunk - 1, size - 1)) for s in range(0, size, chunk)]
    print(f"[INFO] 总大小 {size/1024/1024:.1f} MB，{len(ranges)} 片，{args.threads} 并发", flush=True)

    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futs = {
            ex.submit(fetch, args.url, s, e, parts_dir / f"p{i:04d}", i): i
            for i, (s, e) in enumerate(ranges)
        }
        for f in as_completed(futs):
            i, n = f.result()
            done += n
            print(f"\r[进度] {done/1024/1024:.1f}/{size/1024/1024:.1f} MB  片{i:04d}  {time.time()-t0:.0f}s", end="", flush=True)
    print(flush=True)

    with out.open("wb") as w:
        for i in range(len(ranges)):
            p = parts_dir / f"p{i:04d}"
            w.write(p.read_bytes())
    if out.stat().st_size != size:
        print(f"[ERROR] 合并大小不符: {out.stat().st_size} != {size}", file=sys.stderr)
        return 3
    print(f"[OK] {out}  {out.stat().st_size/1024/1024:.1f} MB  用时 {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
