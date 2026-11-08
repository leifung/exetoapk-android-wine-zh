#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对产出的 APK 做离线质量校验（无需安卓设备）。"""
from __future__ import annotations

import io
import json
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
sys.path.insert(0, str(ROOT / "vendor"))
import zstandard  # noqa: E402

LIGHT = DIST / "exetoapk安卓wine模拟器汉化.apk"
FULL = DIST / "暗黑破坏神II_1.13c_手机版_一体化.apk"


def check(apk: Path, expect_game: bool, expect_name: str) -> dict:
    r = {"apk": apk.name, "exists": apk.exists(), "app_name_expected": expect_name}
    if not apk.exists():
        return r
    r["size_mb"] = round(apk.stat().st_size / 1024 / 1024, 1)
    with zipfile.ZipFile(apk) as z:
        names = z.namelist()
        r["entries"] = len(names)
        r["zip_ok"] = z.testzip() is None
        r["has_manifest"] = "AndroidManifest.xml" in names
        r["has_dex"] = "classes.dex" in names
        arsc = z.read("resources.arsc")
        r["app_name_zh"] = (expect_name.encode("utf-8") in arsc
                            or expect_name.encode("utf-16-le") in arsc)
        hint = "新建容器"
        r["empty_hint_zh"] = (hint.encode("utf-8") in arsc
                              or hint.encode("utf-16-le") in arsc)
        ui = "图形驱动"
        r["ui_zh"] = (ui.encode("utf-8") in arsc
                      or ui.encode("utf-16-le") in arsc)
        r["has_rootfs"] = "assets/rootfs.tzst" in names
        r["templates_stored"] = all(
            z.getinfo(x).compress_type == zipfile.ZIP_STORED
            for x in ("assets/rootfs.tzst", "assets/container_pattern.tzst")
        )
        # aapt2 会重新编码 PNG，不能用字节相等判断；改为与官方原图标比对
        icon = z.read("res/mipmap-xxxhdpi/ic_launcher.png")
        base = ROOT.parent / "tools" / "downloads" / "winlator_base.apk"
        with zipfile.ZipFile(base) as z0:
            original = z0.read("res/mipmap-xxxhdpi-v4/ic_launcher.png")
        r["icon_is_custom"] = icon != original
        r["icon_size_bytes"] = len(icon)

        # 流式检查容器模板（避免把 1GB tar 读进内存）
        f = z.open("assets/container_pattern.tzst")
        reader = zstandard.ZstdDecompressor().stream_reader(f)
        found = {"desktop": 0, "icon": False, "game": False, "note": False, "reg": False}
        desktop_texts: list[str] = []
        member_count = 0
        dirs: set[str] = set()
        missing_parents = 0
        with tarfile.open(fileobj=reader, mode="r|") as t:
            for m in t:
                member_count += 1
                if m.isdir():
                    dirs.add(m.name.rstrip("/"))
                    continue
                parent = m.name.rsplit("/", 1)[0] if "/" in m.name else ""
                if parent and parent not in dirs:
                    missing_parents += 1
                if m.name.endswith(".desktop") and "/Desktop/" in m.name:
                    found["desktop"] += 1
                    fh = t.extractfile(m)
                    if fh:
                        desktop_texts.append(fh.read().decode("utf-8", "replace"))
                elif m.name.endswith("/apps/diablo2.png"):
                    found["icon"] = True
                elif m.name.endswith("/DiabloII/Game.exe"):
                    found["game"] = True
                elif m.name.endswith("_mobile_readme.txt"):
                    found["note"] = True
                elif m.name.endswith(".wine/user.reg"):
                    fh = t.extractfile(m)
                    if fh:
                        reg = fh.read()
                        found["reg"] = (b"Blizzard Entertainment" in reg
                                        and b"InstallPath" in reg
                                        and b"CDKey" in reg)
        desktop_text = "\n".join(desktop_texts)
        r["template_members"] = member_count
        r["template_missing_parents"] = missing_parents
        r["template"] = found
        r["desktop_count"] = found["desktop"]
        r["exec_direct"] = "-direct" in desktop_text
        r["exec_no_txt"] = "-txt" not in desktop_text
        # -nonotify 会屏蔽 Wine 的错误弹窗，崩溃时只表现为黑屏后退回
        r["exec_error_visible"] = "-nonotify" not in desktop_text
        expected_exec = r"C:\\\\DiabloII" if expect_game else r"D:\\\\DiabloII"
        r["exec_path_ok"] = (expected_exec in desktop_text
                             and "Program Files" not in desktop_text)
        r["registry_ok"] = found["reg"]
        r["game_embedded"] = found["game"]
        r["expect_game"] = expect_game
        r["match"] = bool(found["desktop"] >= 5 and found["icon"] and found["note"]
                          and r["app_name_zh"] and r["empty_hint_zh"] and r["ui_zh"]
                          and r["icon_is_custom"] and r["zip_ok"]
                          and r["templates_stored"] and missing_parents == 0
                          and r["exec_direct"] and r["exec_no_txt"]
                          and r["exec_error_visible"] and r["exec_path_ok"]
                          and r["registry_ok"]
                          and found["game"] == expect_game)
    return r


def main() -> int:
    out = [check(LIGHT, False, "exetoapk安卓wine模拟器汉化"),
           check(FULL, True, "暗黑破坏神II 1.13c")]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    (DIST / "校验报告.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    bad = [x for x in out if not x.get("match")]
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
