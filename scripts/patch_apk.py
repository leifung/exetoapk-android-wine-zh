#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 Winlator 11.2 官方 APK 改造成《暗黑破坏神II 1.13c 中文版》专用安卓 APK。

改造内容：
  1. 应用名 / 启动图标 -> 暗黑2 专属
  2. assets/container_pattern.tzst 注入桌面快捷方式 + 图标
  3. （full 模式）把精简游戏本体直接塞进容器模板 -> 装完 APK 新建容器即可开玩
  4. 预置容器/启动参数说明
  5. apktool 回编译 -> zipalign -> 自签名 (v1+v2+v3)

用法：
  python patch_apk.py --mode light   # 150MB 轻量版，需另拷数据包
  python patch_apk.py --mode full    # 一体化版（约 1.2GB）
  python patch_apk.py --mode both    # 两个都生成（默认）
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT.parent / "tools"
JDK = TOOLS / "jdk" / "jdk-17.0.21.0.2+1"
JAVA = JDK / "bin" / "java.exe"
KEYTOOL = JDK / "bin" / "keytool.exe"
APKTOOL = TOOLS / "downloads" / "apktool.jar"
BT = TOOLS / "android-sdk" / "build-tools" / "35.0.0"
ZIPALIGN = BT / "zipalign.exe"
APKSIGNER_JAR = BT / "lib" / "apksigner.jar"
BASE_APK = TOOLS / "downloads" / "winlator_base.apk"
DECOMP = ROOT / "build" / "decompiled"
GAME = ROOT / "game"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
VENDOR = ROOT / "vendor"

sys.path.insert(0, str(VENDOR))
import zstandard  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))
from make_icon import render as render_icon  # noqa: E402

APP_NAME_FULL = "暗黑破坏神II 1.13c"
APP_NAME_LIGHT = "exetoapk安卓wine模拟器汉化"
# 两个版本使用不同的显示名：轻量版作为通用「exe 转 apk 的 Wine 模拟器汉化版」对外发布，
# 一体化版保留游戏名。APP_NAME 在 build_one() 里按版本切换（patch_resources/desktop_content 共用）。
APP_NAME = APP_NAME_LIGHT
KS_PASS = "diablo2mobile"
# 关键：游戏目录必须无空格、无括号。winhandler.exe 用 escapeDOSPath 把空格转成 "\ "，
# 但 "(x86)" 这类括号在命令行解析中容易被当成控制字符，导致找不到 exe 直接退出。
GAME_DIR_IN_WINE = ".wine/drive_c/DiabloII"
DENSITY = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}

# Exec 必须是 Winlator 可解析的转义 DOS 路径；启动参数统一放 [Extra Data] execArgs。
# 四个反斜杠经 unescapeDOSPath 两次 replaceAll 后还原为单反斜杠（check_desktop_exec.py 已实测）。
# 一体化版：游戏本体在容器 C:\DiabloII；轻量版：D: 盘映射手机 Download，数据在 D:\DiabloII。
DOS_FULL = r"C:\\\\DiabloII"
DOS_LIGHT = r"D:\\\\DiabloII"
SEP = r"\\" * 2  # 4 个反斜杠字符

# Shortcut.name 直接取 .desktop 的文件名（Shortcut.java: getBasename），
# 所以文件名即 Shortcuts 页显示的文字，用 ASCII 编号便于用户按顺序试。
# 绝不能加 -nonotify：它是「屏蔽错误报警」，会把崩溃原因吞掉，只表现为黑屏后退回。
LAUNCHERS = [
    ("01-Game-direct-w.desktop",      "Game.exe",     "-direct -w"),
    ("02-PlugY-direct-w.desktop",     "PlugY.exe",    "-direct -w"),
    ("03-D2Loader-direct-w.desktop",  "D2Loader.exe", "-direct -w"),
    ("04-Game-w-only.desktop",        "Game.exe",     "-w"),
    ("05-Game-3dfx-direct-w.desktop", "Game.exe",     "-3dfx -direct -w"),
]
DESKTOP_NAME = LAUNCHERS[0][0]

# Winlator 的 Shortcuts 页只扫描「已创建容器」的 Desktop 目录，首次启动不会自动建容器。
# 把官方的 "No items to display" 换成可操作指引，避免用户误以为包坏了。
EMPTY_HINT = ("首次使用：请先到 Containers（容器）页点右上角 + 新建容器，"
              "等待解压完成后再回到本页。若已建容器仍为空，请删除该容器后重建。")


def desktop_content(exec_path: str, exec_args: str) -> str:
    return f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Exec=wine {exec_path}
Icon=diablo2
StartupWMClass=game.exe

[Extra Data]
execArgs={exec_args}
screenSize=800x600
dxwrapper=wined3d
graphicsDriver=virgl
forceFullscreen=0
"""


def wine_reg_block(install_path: str, is_system: bool, original: bytes) -> bytes:
    """给 Wine 注册表补上 Diablo II 的 InstallPath / Save Path / CDKey。

    3DM 绿色版在 PC 上能跑，是因为宿主 Windows 注册表里已有 Blizzard 项，
    或由 D2Loader 绕过；手机容器是全新 Wine，user.reg 里完全没有这些键，
    1.13c 启动读不到安装路径/CDKey 会直接退出。Wine .reg 中路径反斜杠需双写。
    """
    root = install_path.rstrip("\\")
    p = (root + "\\").replace("\\", "\\\\")
    save = (root + "\\Save\\").replace("\\", "\\\\")
    ts = int(time.time())
    values = (
        f'"InstallPath"="{p}"\n'
        f'"Save Path"="{save}"\n'
        '"CDKey"="1234567890123456"\n'
        '"Serial"="1234567890123456"\n'
        '"D2XCDKey"="1234567890123456"\n'
        '"D2XSerial"="1234567890123456"\n'
        '"Owner Name"="Player"\n'
    )
    sections = ["Software\\\\Blizzard Entertainment\\\\Diablo II"]
    # system.reg 是 #arch=win64；32 位游戏读 HKLM 会被重定向到 Wow6432Node，两份都写
    if is_system:
        sections.append("Software\\\\Wow6432Node\\\\Blizzard Entertainment\\\\Diablo II")
    block = "".join(f"\n[{s}] {ts}\n{values}" for s in sections)
    return original.rstrip(b"\r\n") + b"\n" + block.encode("utf-8")


def run(cmd: list, desc: str, timeout: int = 3600) -> None:
    print(f"\n>>> {desc}", flush=True)
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       timeout=timeout, encoding="utf-8", errors="replace")
    if r.stdout.strip():
        print("\n".join(r.stdout.strip().splitlines()[-15:]), flush=True)
    if r.returncode != 0:
        print(r.stderr[-3000:], file=sys.stderr, flush=True)
        raise RuntimeError(f"{desc} 失败 (exit {r.returncode})")


def _ti(name: str, size: int = 0, mode: int = 0o644, is_dir: bool = False) -> tarfile.TarInfo:
    t = tarfile.TarInfo(name)
    t.size = size
    t.mode = mode
    t.mtime = int(time.time())
    t.uid = t.gid = 0
    t.uname = t.gname = "root"
    if is_dir:
        t.type = tarfile.DIRTYPE
        t.mode = 0o755
    return t


def patch_container_pattern(embed_game: bool) -> int:
    """重写容器模板：注入注册表、桌面快捷方式、图标，可选注入游戏本体。

    历史修复：
    1) Java 端 TarCompressorUtils.extract 只在遇到「目录条目」时 mkdirs，
       **不会**为文件自动创建父目录。缺一个父目录就抛 FileNotFoundException，
       extract 返回 false，createContainer 随即删掉整个容器目录。
    2) 游戏目录从 "Program Files (x86)/Diablo II" 改成无空格无括号的 DiabloII，
       避免 winhandler.exe 命令行解析失败。
    3) 补写 Wine 注册表 Blizzard Entertainment\\Diablo II 项（InstallPath 等）。
    4) 去掉 -nonotify（屏蔽错误框），预置多个启动方案供真机逐个验证。
    """
    tzst = DECOMP / "assets" / "container_pattern.tzst"
    print(f"\n>>> 解压容器模板 {tzst.stat().st_size/1024/1024:.1f} MB", flush=True)
    with tzst.open("rb") as f:
        raw = zstandard.ZstdDecompressor().stream_reader(f).read()
    src = tarfile.open(fileobj=io.BytesIO(raw))
    tmp_tar = BUILD / "container_pattern.tar"

    # tar 内的中文文件名在 Java commons-compress 下可能乱码，统一映射为 ASCII
    ascii_name = {
        "PlugY.ini.带地图插件": "PlugY.ini.maphack",
        "快捷键说明.txt": "readme_hotkeys.txt",
        "物品代码.txt": "item_codes.txt",
        "物品配置说明.txt": "item_config_readme.txt",
        "颜色显示.html": "color_codes.html",
    }

    def safe_rel(rel: str) -> str:
        return "/".join(ascii_name.get(p, p) for p in rel.split("/"))

    base_dos = DOS_FULL if embed_game else DOS_LIGHT
    install_path = "C:\\DiabloII" if embed_game else "D:\\DiabloII"
    note = (
        "暗黑破坏神II 1.13c 中文版 / 手机端说明\r\n"
        "========================================\r\n"
        "快捷方式页有 01~05 五个启动方案，请按编号顺序点，哪个能进就用哪个。\r\n"
        "  01 Game.exe -direct -w       首选：直连主程序，无进程注入\r\n"
        "  02 PlugY.exe -direct -w      大箱子（原版既定启动方式）\r\n"
        "  03 D2Loader.exe -direct -w   免CD加载器（旧方案）\r\n"
        "  04 Game.exe -w               排除中文 Data 目录问题\r\n"
        "  05 Game.exe -3dfx -direct -w D2DX 高清渲染路径\r\n"
        "必需参数：-direct   （不加会丢失中文，从 Data 目录加载汉化）\r\n"
        "禁止参数：-txt      （本版本加此参数会在片头后直接退出）\r\n"
        "禁止参数：-nonotify （屏蔽错误弹窗，会让崩溃原因不可见）\r\n"
        "已预置注册表：Blizzard Entertainment\\Diablo II 的 InstallPath / Save Path / CDKey\r\n"
        f"游戏目录：{install_path}\r\n"
        "地图插件：把 PlugY.ini.maphack 重命名为 PlugY.ini 即可启用\r\n"
        "注意：本包已移除过场动画与音乐 MPQ 以节省手机空间，不影响游戏流程。\r\n"
    )

    # 预读 Wine 注册表，准备改写（追加 Blizzard 项）
    reg_patch: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as probe:
        for m in probe:
            if m.name in (".wine/user.reg", ".wine/system.reg"):
                fh = probe.extractfile(m)
                if fh:
                    reg_patch[m.name] = wine_reg_block(
                        install_path, m.name.endswith("system.reg"), fh.read())
    print(f">>> 准备改写 {len(reg_patch)} 个 Wine 注册表文件（InstallPath={install_path}）", flush=True)

    # 1) 先收集全部待注入文件：(归档路径, 源文件 Path 或 None, 内存字节)
    payload: list[tuple[str, Path | None, bytes]] = []
    for fname, exe, args in LAUNCHERS:
        exec_path = f"{base_dos}{SEP}{exe}"
        payload.append((f".wine/drive_c/users/xuser/Desktop/{fname}", None,
                        desktop_content(exec_path, args).encode("utf-8")))
    print(f">>> 预置 {len(LAUNCHERS)} 个启动方案，Exec 根目录 {base_dos}", flush=True)
    for sz in (16, 24, 32, 48, 64, 128, 256):
        payload.append((f".local/share/icons/hicolor/{sz}x{sz}/apps/diablo2.png",
                        None, render_icon(sz)))
    game_dirs: list[str] = []
    if embed_game:
        for p in sorted(GAME.rglob("*")):
            rel = safe_rel(str(p.relative_to(GAME)).replace("\\", "/"))
            arc = f"{GAME_DIR_IN_WINE}/{rel}"
            if p.is_dir():
                game_dirs.append(arc)
            else:
                payload.append((arc, p, b""))
        game_dirs.append(GAME_DIR_IN_WINE)
        # 注册表 Save Path 指向这里，先建出来（游戏有时不会自己创建）
        payload.append((f"{GAME_DIR_IN_WINE}/Save/.keep", None, b""))
        note_path = f"{GAME_DIR_IN_WINE}/_mobile_readme.txt"
    else:
        note_path = ".wine/drive_c/users/xuser/Desktop/_mobile_readme.txt"
    payload.append((note_path, None, note.encode("gbk", errors="replace")))

    added = 0
    with tmp_tar.open("wb") as fo:
        dst = tarfile.open(fileobj=fo, mode="w", format=tarfile.GNU_FORMAT)
        existing_dirs: set[str] = set()
        for m in src:
            info = tarfile.TarInfo(m.name)
            info.mode, info.uid, info.gid = m.mode, m.uid, m.gid
            info.uname, info.gname = m.uname, m.gname
            info.mtime, info.type = m.mtime, m.type
            info.linkname, info.size = m.linkname, m.size
            if m.name in reg_patch:
                data = reg_patch[m.name]
                info.size = len(data)
                dst.addfile(info, io.BytesIO(data))
                continue
            fobj = src.extractfile(m) if m.isfile() else None
            dst.addfile(info, fobj)
            if m.isdir():
                existing_dirs.add(m.name.rstrip("/"))
        src.close()

        # 2) 补齐所有祖先目录条目（父目录必须先于文件出现）
        needed: set[str] = set(game_dirs)
        for arc, _, _ in payload:
            parts = arc.split("/")
            for i in range(1, len(parts)):
                needed.add("/".join(parts[:i]))
        new_dirs = sorted(needed - existing_dirs, key=lambda x: (x.count("/"), x))
        for d in new_dirs:
            dst.addfile(_ti(d + "/", is_dir=True), None)
            added += 1
        print(f">>> 补齐 {len(new_dirs)} 个目录条目（Java 解压不自动建父目录）", flush=True)

        # 3) 再写文件条目
        for arc, srcfile, data in payload:
            if srcfile is not None:
                info = _ti(arc, srcfile.stat().st_size)
                with srcfile.open("rb") as fh:
                    dst.addfile(info, fh)
            else:
                dst.addfile(_ti(arc, len(data)), io.BytesIO(data))
            added += 1
        dst.close()

    print(f">>> 重新压缩容器模板（新增 {added} 项，tar {tmp_tar.stat().st_size/1024/1024:.1f} MB）", flush=True)
    tmp_tzst = BUILD / "container_pattern.new.tzst"
    with tmp_tzst.open("wb") as fo:
        cctx = zstandard.ZstdCompressor(level=3, threads=4)
        with cctx.stream_writer(fo) as w:
            with tmp_tar.open("rb") as fi:
                shutil.copyfileobj(fi, w, 4 * 1024 * 1024)
    tmp_tar.unlink()
    tmp_tzst.replace(tzst)
    print(f">>> 新模板 {tzst.stat().st_size/1024/1024:.1f} MB", flush=True)
    return added


def patch_resources() -> None:
    import re
    # 应用名（所有语言目录里的同名字符串一并替换）
    n = 0
    for f in (DECOMP / "res").rglob("strings*.xml"):
        t = f.read_text(encoding="utf-8", errors="replace")
        if 'name="app_name"' in t:
            t2 = re.sub(r'(<string name="app_name">)[^<]*(</string>)',
                        lambda m: m.group(1) + APP_NAME + m.group(2), t)
            if t2 != t:
                f.write_text(t2, encoding="utf-8")
                n += 1
    print(f">>> 应用名改为「{APP_NAME}」，修改 {n} 个 strings 文件", flush=True)

    # 空列表文案：官方是 "No items to display"，用户会误以为 APK 坏了。
    # 改成可直接照做的操作指引（values / values-pt / values-ru 三处）。
    m = 0
    for f in (DECOMP / "res").rglob("strings*.xml"):
        t = f.read_text(encoding="utf-8", errors="replace")
        if 'name="no_items_to_display"' in t:
            t2 = re.sub(r'(<string name="no_items_to_display">)[^<]*(</string>)',
                        lambda x: x.group(1) + EMPTY_HINT + x.group(2), t)
            if t2 != t:
                f.write_text(t2, encoding="utf-8")
                m += 1
    print(f">>> 空列表提示改为操作指引，修改 {m} 个 strings 文件", flush=True)

    # 启动图标：apktool 反编译后目录为 res/mipmap-<density>/（不带 -v4）
    k = 0
    for p in (DECOMP / "res").rglob("ic_launcher*.png"):
        density = p.parent.name.replace("mipmap-", "").split("-")[0]
        size = DENSITY.get(density)
        if not size:
            continue
        p.write_bytes(render_icon(size, "foreground" in p.name))
        k += 1
    print(f">>> 替换 {k} 个启动图标", flush=True)

    # 关键：让 .tzst 以 ZIP_STORED（不压缩）方式打包。
    # Android AssetManager 读取「压缩过的」asset 会整块解压进内存；官方模板只有 7MB 无碍，
    # 一体化版 container_pattern.tzst 接近 1GB，压缩打包会在创建容器时直接 OOM。
    yml = DECOMP / "apktool.yml"
    t = yml.read_text(encoding="utf-8")
    if "tzst" not in t:
        if "doNotCompress:" in t:
            t = t.replace("doNotCompress:\n", "doNotCompress:\n- tzst\n", 1)
        else:
            t = t.rstrip() + "\ndoNotCompress:\n- tzst\n"
        yml.write_text(t, encoding="utf-8")
        print(">>> apktool.yml 已加入 tzst 不压缩规则", flush=True)

    # 附赠启动参数配置（APK 内可见，便于查阅）
    extra = DECOMP / "assets" / "diablo2"
    extra.mkdir(parents=True, exist_ok=True)
    src = GAME / "_mobile" / "launch_profiles.json"
    if src.exists():
        (extra / "launch_profiles.json").write_bytes(src.read_bytes())


def chinese_ui() -> None:
    """强制全中文界面。

    官方 values-zh-rCN 只翻译 90/436 条，且系统语言非中文时完全不生效。
    做法：以默认 values 为基准生成「中文优先」词表，再把它同步写入所有
    values*/strings*.xml，使任何系统语言下都显示同一套中文文案。
    """
    import re
    sys.path.insert(0, str(ROOT / "scripts"))
    from zh_strings import ZH

    res = DECOMP / "res"
    default = res / "values" / "strings.xml"
    pat = re.compile(r'<string name="([^"]+)"[^>]*>(.*?)</string>', re.S)
    en = dict(pat.findall(default.read_text(encoding="utf-8")))

    # 官方中文包（90 条）打底，自建词表覆盖并补齐
    official: dict[str, str] = {}
    for d in ("values-zh-rCN", "values-zh-rHK", "values-zh-rTW"):
        p = res / d / "strings.xml"
        if p.exists():
            official.update(dict(pat.findall(p.read_text(encoding="utf-8"))))
    mapping = {**official, **ZH}

    fmt = re.compile(r"%(?:\d+\$)?[a-zA-Z]")
    final: dict[str, str] = {}
    skipped = 0
    for k, v in en.items():
        new = mapping.get(k)
        if new is None:
            final[k] = v
        elif fmt.findall(v) != fmt.findall(new) or "&lt;" in v or v.startswith("@"):
            # 格式符、HTML 标签或资源引用不一致会让 aapt2 编译失败 / 显示异常
            final[k] = v
            skipped += 1
        else:
            final[k] = new

    tag = re.compile(r'(<string name="([^"]+)"[^>]*>)(.*?)(</string>)', re.S)
    n_files = n_hit = 0
    for f in res.rglob("strings*.xml"):
        t = f.read_text(encoding="utf-8", errors="replace")
        hits = [0]

        def repl(m: re.Match) -> str:
            name = m.group(2)
            if name in final:
                hits[0] += 1
                return m.group(1) + final[name] + m.group(4)
            return m.group(0)

        t2 = tag.sub(repl, t)
        if t2 != t:
            f.write_text(t2, encoding="utf-8")
            n_files += 1
            n_hit += hits[0]
    print(f">>> 中文界面：词表 {len(mapping)} 条，替换 {n_hit} 处 / {n_files} 个 strings 文件，"
          f"保留 {skipped} 条高风险文案", flush=True)


def ensure_keystore() -> Path:
    ks = ROOT / "keystore" / "diablo2.jks"
    if ks.exists():
        return ks
    ks.parent.mkdir(parents=True, exist_ok=True)
    run([KEYTOOL, "-genkeypair", "-v", "-keystore", ks, "-alias", "diablo2",
         "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
         "-storepass", KS_PASS, "-keypass", KS_PASS,
         "-dname", "CN=Diablo II Mobile, OU=Personal, O=Personal, L=Beijing, ST=Beijing, C=CN"],
        "生成自签名证书")
    return ks


def build_one(tag: str, embed: bool) -> Path:
    global APP_NAME
    APP_NAME = APP_NAME_FULL if embed else APP_NAME_LIGHT
    print(f"\n{'='*66}\n  构建 {tag} 版（{'内置游戏本体' if embed else '不含游戏本体'}）"
          f"\n  应用名：{APP_NAME}\n{'='*66}", flush=True)
    # 每个版本都重新刷一遍资源：both 模式下两个版本的 app_name 不同，
    # 而 chinese_ui() 会把 values/strings.xml 的 app_name 同步到所有语言目录。
    patch_resources()
    chinese_ui()
    patch_container_pattern(embed)
    unsigned = BUILD / f"{tag}_unsigned.apk"
    aligned = BUILD / f"{tag}_aligned.apk"
    final = DIST / ("暗黑破坏神II_1.13c_手机版_一体化.apk" if embed
                    else f"{APP_NAME_LIGHT}.apk")

    run([JAVA, "-Xmx4g", "-jar", APKTOOL, "b", "-o", unsigned, DECOMP],
        "apktool 回编译")
    run([ZIPALIGN, "-p", "-f", "4", unsigned, aligned], "zipalign 对齐")
    ks = ensure_keystore()
    run([JAVA, "-jar", APKSIGNER_JAR, "sign",
         "--ks", ks, "--ks-pass", f"pass:{KS_PASS}", "--key-pass", f"pass:{KS_PASS}",
         "--v1-signing-enabled", "true", "--v2-signing-enabled", "true",
         "--v3-signing-enabled", "true", "--out", final, aligned],
        "APK 签名 (v1+v2+v3)")
    run([JAVA, "-jar", APKSIGNER_JAR, "verify", "--verbose", final], "验证签名")
    with zipfile.ZipFile(final) as z:
        assert z.testzip() is None, "APK 压缩包校验失败"
        names = z.namelist()
        assert "AndroidManifest.xml" in names and "classes.dex" in names
    print(f">>> [OK] {final}  {final.stat().st_size/1024/1024:.1f} MB", flush=True)
    return final


def build_data_pack() -> Path:
    out = DIST / "DiabloII_数据包.zip"
    print("\n>>> 生成独立游戏数据包（轻量版配套）", flush=True)
    files = [p for p in GAME.rglob("*") if p.is_file()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for i, p in enumerate(files):
            z.write(p, "DiabloII/" + str(p.relative_to(GAME)).replace("\\", "/"))
            if i % 150 == 0:
                print(f"\r    打包 {i}/{len(files)}", end="", flush=True)
    print(f"\r>>> [OK] {out}  {out.stat().st_size/1024/1024:.1f} MB", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("light", "full", "both"), default="both")
    args = ap.parse_args()

    for p in (JAVA, APKTOOL, ZIPALIGN, APKSIGNER_JAR, BASE_APK):
        if not p.exists():
            print(f"[ERROR] 缺少 {p}", file=sys.stderr)
            return 2
    DIST.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)

    # 每次构建前，恢复一份干净的官方模板
    with zipfile.ZipFile(BASE_APK) as z:
        (DECOMP / "assets" / "container_pattern.tzst").write_bytes(
            z.read("assets/container_pattern.tzst"))

    results = {}
    if args.mode in ("light", "both"):
        results["light"] = str(build_one("light", False))
        results["data_pack"] = str(build_data_pack())
    if args.mode in ("full", "both"):
        # full 也使用原始模板重新注入，避免叠加
        with zipfile.ZipFile(BASE_APK) as z:
            (DECOMP / "assets" / "container_pattern.tzst").write_bytes(
                z.read("assets/container_pattern.tzst"))
        results["full"] = str(build_one("full", True))

    report = {
        "base": "Winlator 11.2.0 (LGPL-2.1)",
        "app_name": {"light": APP_NAME_LIGHT, "full": APP_NAME_FULL},
        "package": "com.winlator",
        "version": "11.2 / 1.13c / v4",
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "artifacts": results,
        "sizes_mb": {k: round(Path(v).stat().st_size / 1024 / 1024, 1)
                     for k, v in results.items()},
        "notice": "仅限个人自用；内置 Wine/Box64 等 LGPL/GPL 组件，游戏数据版权归暴雪/权利人所有，不得分发。",
    }
    (DIST / "构建报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print("\n" + json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
