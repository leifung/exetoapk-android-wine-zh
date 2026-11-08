#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 PC 版《暗黑破坏神II 1.13c 中文版》生成安卓 / Winlator 端精简游戏包。

用法：
    python prepare_game.py                    # 默认精简（去视频+音乐，约 1.1 GB）
    python prepare_game.py --include-music   # 保留音乐（约 1.5 GB）
    python prepare_game.py --src <路径>      # 指定源目录

不改动源目录任何文件，全部复制到 port/game/ 下。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

DEFAULT_SRC = r"D:\3DMGAME_DiabloII.V1.13C.CHS.Green\Diablo II原始\Diablo II"
ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "game"

# 根目录只保留这些扩展名（游戏运行必需）
KEEP_EXT = {".exe", ".dll", ".mpq", ".ini", ".cfg", ".json", ".lng", ".key"}

# 明确剔除：过场动画、PC 高清补丁、安装/补丁工具、修改器
DROP_EXACT = {
    # 手机端可省的过场动画（约 527 MB）
    "D2Video.mpq", "D2xVideo.mpq",
    # 高清宽屏补丁资源（Wine 下走 Glide 容易黑屏）
    "d2dx_sgd2freeres.mpq", "d2dx_sgd2freeres.dll", "d2dx_sgd2freeres.json",
    "d2fps.dll", "d2fps.log", "d2dx.cfg", "d2dx_log.txt", "SGD2FreeRes.json",
    # 安装器、补丁器、PC 启动器、日志
    "PatchGoldLimit.exe", "PatchUniquePurple.exe", "PatchD2gfxDll.exe",
    "RestoreD2gfxDll.exe", "RunEasy.exe", "BNUpdate.exe", "D2VidTst.exe",
    "unins000.exe", "unins000.dat", "启动游戏.exe", "Crashdump",
    "BnetLog.txt", "D2261103.txt", "D2261104.txt", "D2261105.txt", "D2261107.txt",
    "README.md", "使用说明.md", "3dmConfig.ini",
}
MUSIC_FILES = {"D2Music.mpq", "D2xMusic.mpq"}          # 约 381 MB
DROP_PREFIX = ("_补丁备份_",)
KEEP_DIRS = ("Data", "Save", "Plugin", "PlugY", "3dm", "licenses")
DROP_DIRS = {"增强补丁", "修改器"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def patch_plugy_ini(path: Path) -> None:
    """去掉 -3dfx（Glide 在 Wine 下易黑屏），保留 -direct（中文必需）。"""
    if not path.exists():
        return
    raw = path.read_bytes()
    raw = raw.replace(b"Param=-3dfx -direct", b"Param=-direct")
    raw = raw.replace(b"Param=-direct -3dfx", b"Param=-direct")
    # 主配置默认不注入地图 hack DLL（Wine 下 DLL 注入易崩）；另存"带地图插件"版供替换
    opt = path.with_name("PlugY.ini.带地图插件")
    opt.write_bytes(raw)
    path.write_bytes(raw.replace(b"DllToLoad=.\\Plugin\\D2HackMap.dll", b"DllToLoad="))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--include-music", action="store_true")
    ap.add_argument("--include-video", action="store_true")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_dir():
        print(f"[ERROR] 源目录不存在: {src}", file=sys.stderr)
        return 2

    drop = set(DROP_EXACT)
    if not args.include_music:
        drop |= MUSIC_FILES
    if args.include_video:
        drop -= {"D2Video.mpq", "D2xVideo.mpq"}

    if DST.exists():
        print(f"[INFO] 清理旧输出 {DST}")
        shutil.rmtree(DST)
    DST.mkdir(parents=True)

    copied: list[Path] = []
    skipped: list[str] = []

    for entry in sorted(src.iterdir()):
        if entry.is_dir():
            if entry.name in DROP_DIRS or entry.name.startswith(DROP_PREFIX):
                skipped.append(f"[目录] {entry.name}")
                continue
            if entry.name in KEEP_DIRS:
                target = DST / entry.name
                shutil.copytree(entry, target, dirs_exist_ok=True)
                copied.extend(p for p in target.rglob("*") if p.is_file())
            else:
                skipped.append(f"[目录] {entry.name}")
            continue
        if entry.suffix.lower() not in KEEP_EXT or entry.name in drop:
            skipped.append(f"[文件] {entry.name}")
            continue
        shutil.copy2(entry, DST / entry.name)
        copied.append(DST / entry.name)

    patch_plugy_ini(DST / "PlugY.ini")

    # 启动配置：供壳 APK / 快捷方式读取
    cfg_dir = DST / "_mobile"
    cfg_dir.mkdir(exist_ok=True)
    profiles = {
        "package": "Diablo II 1.13c CHS / Lord of Destruction",
        "note": "-direct 为中文必需；-txt 会导致本版本片头后退出，切勿使用；"
                "-notitle 跳过片头以兼容已移除的 D2Video.mpq",
        "profiles": [
            {
                "id": "vanilla",
                "name": "原版（推荐先测这个）",
                "executable": "D2Loader.exe",
                "args": "-direct -w -notitle -nonotify",
                "working_dir": ".",
            },
            {
                "id": "plugy",
                "name": "大箱子 PlugY（原版跑通后再换）",
                "executable": "PlugY.exe",
                "args": "-direct -w -notitle",
                "working_dir": ".",
            },
            {
                "id": "fallback",
                "name": "无声低画质排障",
                "executable": "D2Loader.exe",
                "args": "-direct -w -notitle -ns -lq -nonotify",
                "working_dir": ".",
            },
        ],
        "container": {
            "resolution": "800x600",
            "graphics_driver": "通用: VirGL；骁龙/Adreno: Turnip+Zink",
            "dx_wrapper": "CNC DDraw（老 DirectDraw 游戏）或 WineD3D",
            "audio_driver": "PulseAudio",
            "box64_preset": "Stability（跑通后可试 Performance）",
            "windows_version": "Windows XP / Windows 7",
            "video_memory_mb": 2048,
            "env": {"MESA_EXTENSION_MAX_YEAR": "2003"},
        },
    }
    (cfg_dir / "launch_profiles.json").write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest = {
        "source": str(src),
        "include_music": args.include_music,
        "include_video": args.include_video,
        "file_count": len(copied),
        "total_bytes": sum(p.stat().st_size for p in copied),
        "files": [],
    }
    for p in sorted(copied):
        manifest["files"].append({
            "path": str(p.relative_to(DST)).replace("\\", "/"),
            "size": p.stat().st_size,
            "sha256": sha256(p),
        })
    (ROOT / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    mb = manifest["total_bytes"] / 1024 / 1024
    print(f"[OK] 输出目录 : {DST}")
    print(f"[OK] 文件数量 : {manifest['file_count']}")
    print(f"[OK] 总体积   : {mb:.1f} MB ({mb/1024:.2f} GB)")
    print(f"[OK] 清单     : {ROOT / 'MANIFEST.json'}")
    print(f"[OK] 跳过     : {len(skipped)} 项")
    print("[OK] 已生成 _mobile/launch_profiles.json（3 套启动参数 + 容器配置）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
