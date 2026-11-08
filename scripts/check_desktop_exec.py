#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精确复现 Winlator StringUtils.unescapeDOSPath，验证 .desktop Exec 里的路径写法。

v4 起直接读取 patch_apk.py 的实际常量，逐个校验 5 个启动方案在一体化版
(C:\\DiabloII) 和轻量版 (D:\\DiabloII) 下的 Exec 是否都能还原成正确 DOS 路径。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import patch_apk as p  # noqa: E402


def unescape(path: str) -> str:
    # Java: replaceAll("\\\\([^\\\\]+)", "$1") == regex \\([^\\]+) -> group1
    for _ in range(2):
        path = re.sub(r"\\([^\\]+)", r"\1", path)
    # Java: replaceAll("\\\\\\\\", "\\\\") == 两个字面反斜杠 -> 一个
    path = re.sub(r"\\\\", lambda m: "\\", path)
    return path.strip()


def escape(path: str) -> str:
    # Java: path.replace("\\","\\\\").replace(" ","\\ ")
    return path.replace("\\", "\\\\").replace(" ", "\\ ")


ok = True
for label, base, drive in (("一体化", p.DOS_FULL, "C"), ("轻量", p.DOS_LIGHT, "D")):
    print(f"=== {label}版 ===")
    for fname, exe, _args in p.LAUNCHERS:
        exec_path = f"{base}{p.SEP}{exe}"
        target = f"{drive}:\\DiabloII\\{exe}"
        out = unescape(" " + exec_path)  # Shortcut 传入时带一个前导空格
        good = out == target
        ok &= good
        print(f"  {fname:32s} -> {out:34s} {'OK' if good else 'FAIL'}")
        assert " " not in out, "路径中不得含空格（winhandler.exe 命令行解析风险）"
    print()

print("旧路径的四反斜杠写法（回归对照）:")
old = r"C:\\\\Program Files (x86)\\\\Diablo II\\\\D2Loader.exe"
print("  ", unescape(old))
print()
print("RESULT:", "ALL PASS" if ok else "FAILED")
raise SystemExit(0 if ok else 1)
