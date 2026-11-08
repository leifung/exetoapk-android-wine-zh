#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC 端一键部署（轻量版配套，需要手机开启 USB 调试）。

    python deploy.py                 # 安装 APK + 推送游戏数据
    python deploy.py --apk-only      # 只装 APK
    python deploy.py --data-only     # 只推游戏数据
    python deploy.py --serial <id>   # 指定设备

一体化版不需要本脚本：装完 APK 直接在 Winlator 里新建容器即可。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADB = ROOT.parent / "tools" / "android-sdk" / "platform-tools" / "adb.exe"
APK = ROOT / "dist" / "暗黑破坏神II_1.13c_手机版_轻量.apk"
GAME = ROOT / "game"
REMOTE_DIR = "/sdcard/Download/DiabloII"


def adb(args: list[str], *, capture: bool = False, timeout: int = 3600):
    cmd = [str(ADB)] + args
    r = subprocess.run(cmd, capture_output=capture, text=True,
                       timeout=timeout, encoding="utf-8", errors="replace")
    if r.returncode != 0 and not capture:
        print(r.stderr[-1500:], file=sys.stderr)
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk-only", action="store_true")
    ap.add_argument("--data-only", action="store_true")
    ap.add_argument("--serial", default="")
    args = ap.parse_args()

    if not ADB.exists():
        print(f"[ERROR] 找不到 adb: {ADB}", file=sys.stderr)
        return 2
    base = ["-s", args.serial] if args.serial else []

    r = adb(base + ["devices"], capture=True)
    devices = [l.split("\t")[0] for l in r.stdout.splitlines()
               if "\tdevice" in l]
    if not devices:
        print("[ERROR] 未检测到已授权设备。请在手机上：设置 → 开发者选项 → USB 调试，"
              "连接电脑后点「允许 USB 调试」。", file=sys.stderr)
        print(r.stdout)
        return 3
    print(f"[OK] 设备: {', '.join(devices)}")

    if not args.data_only:
        if not APK.exists():
            print(f"[ERROR] 缺少 {APK}", file=sys.stderr)
            return 2
        print(f">>> 安装 {APK.name}（{APK.stat().st_size/1024/1024:.0f} MB）")
        adb(base + ["install", "-r", str(APK)])

    if not args.apk_only:
        if not GAME.is_dir():
            print(f"[ERROR] 缺少游戏目录 {GAME}", file=sys.stderr)
            return 2
        n = sum(1 for p in GAME.rglob("*") if p.is_file())
        mb = sum(p.stat().st_size for p in GAME.rglob("*") if p.is_file()) / 1024 / 1024
        print(f">>> 推送游戏数据 {n} 个文件 / {mb:.0f} MB -> {REMOTE_DIR}")
        print("    （USB 2.0 约需 1-3 分钟，请保持连接）", flush=True)
        adb(base + ["shell", "mkdir", "-p", REMOTE_DIR])
        adb(base + ["push", str(GAME) + "/.", REMOTE_DIR + "/"])

    print("""
[完成] 接下来在手机上：
  1. 打开「暗黑破坏神II」App，等首次初始化（解压 Wine 运行环境，约 1-3 分钟）
  2. 点右上角 + 新建容器：分辨率 800x600，其余先用默认
  3. 进入容器 → 打开 D: 盘 → Download/DiabloII → 右键 D2Loader.exe → Create Shortcut
  4. 在快捷方式设置里把启动参数填成： -direct -w -notitle -nonotify
  5. 回到 Shortcuts 页点图标开玩；中文丢失=漏了 -direct，加了 -txt 会片头后退出
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
