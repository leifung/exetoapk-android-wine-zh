# exetoapk安卓wine模拟器汉化

基于 [Winlator 11.2.0](https://github.com/brunodev85/winlator) 的安卓端 Windows 程序兼容层（Wine + Box64）**全中文界面定制版**，轻量版约 154 MB。

> 名称中的 `wine` 指 Wine 兼容层，`exetoapk` 表示把 PC 上的 exe 放进安卓容器运行。包名保持 `com.winlator`，与官方版签名不同，**不能共存**，安装前需先卸载官方 Winlator。

## 相对官方 11.2.0 改了什么

| 问题 | 官方 11.2.0 | 本版 |
|---|---|---|
| 中文界面 | `values-zh-rCN` 仅翻译 90/436 条，系统语言非中文时完全不生效 | 401 条中文词表同步写入所有语言目录，任意系统语言下都显示中文（[词表](scripts/zh_strings.py)） |
| 快捷方式页空白 | 显示 `No items to display`，用户以为包坏了 | 换成「先到容器页新建容器」的可操作指引 |
| 新建容器后没有游戏 | 注入文件缺父目录 tar 条目，Java `TarCompressorUtils.extract()` 抛异常后直接删掉容器 | 补齐全部 18 个祖先目录条目，离线校验 `template_missing_parents=0` |
| 大体积 asset 导致 OOM | `.tzst` 默认压缩进 APK | `apktool.yml` 加 `doNotCompress`，以 ZIP_STORED 打包 |
| 启动路径 | — | 统一用无空格无括号的 `C:\DiabloII` / `D:\DiabloII`，避开 `winhandler.exe` 的命令行解析问题 |
| 崩溃排障 | 错误框被 `-nonotify` 吞掉 | 去掉该参数，预置 5 个编号启动方案，按顺序逐个试 |
| 应用名 / 图标 | 官方 Winlator | 改为「exetoapk安卓wine模拟器汉化」+ 自制暗色风格图标 |

改造全部集中在**资源与容器模板数据层面**，未修改 Winlator 的 Java / Native 代码逻辑。所有脚本见 [`scripts/`](scripts/)。

## 这个仓库不含什么

- **不含任何游戏 / 商业软件数据**：无 MPQ、EXE、DLL、字体、音视频、CD-KEY。
- 不含 Winlator 官方原版 APK 二进制（请从[上游 Release](https://github.com/brunodev85/winlator/releases/tag/v11.2.0) 获取）。
- 不含内置 1 GB 游戏数据的一体化版与独立数据包，**也不会在此发布**。
- 容器内预置的 5 个 `.desktop` 只是**路径示例**，指向 `D:\DiabloII\*.exe`；设备里没有对应文件时点击不会启动任何程序。

## 下载与安装

从本仓库 **Releases** 下载 `exetoapk安卓wine模拟器汉化.apk`（153.8 MB），校验值见 [`SHA256SUMS.txt`](SHA256SUMS.txt)。

1. 允许「安装未知来源应用」；已装官方 Winlator 的先卸载。
2. 首次打开 → **容器（Containers）** 页 → 右上角 `+` 新建容器，等待解压完成。
3. 回到 **快捷方式（Shortcuts）** 页，即可看到 01~05 五个示例启动项。
4. 容器建议：Box64 预设 `Stability`、图形驱动 `VirGL`、DX Wrapper `wined3d`、分辨率 `800x600`。

### 跑自己的 exe

轻量版把容器 `D:` 盘映射到手机 `Download` 目录。把 PC 程序整体拷到 `Download/DiabloII/`，或修改 `scripts/patch_apk.py` 里 `LAUNCHERS` / `DOS_LIGHT` 的 `Exec` 路径后重新构建。注意 `.desktop` 的 `Exec` 需要四个反斜杠才能通过 Winlator 的 `unescapeDOSPath()` 还原，详见 [`scripts/check_desktop_exec.py`](scripts/check_desktop_exec.py)。

## 自行构建

依赖：Microsoft OpenJDK 17、Android SDK Build-Tools 35.0.0（`zipalign` / `apksigner`）、Apktool 2.12.1、Python 3.10+（`zstandard`、`Pillow`）、官方 Winlator 11.2.0 APK 作为 `tools/downloads/winlator_base.apk`。

```bash
python scripts/patch_apk.py --mode light     # 轻量版
python scripts/verify_apk.py                # 离线校验，输出 校验报告.json
```

产物在 `dist/`。脚本会用工程内 keystore 做 v1+v2+v3 自签名；证书与口令**不随仓库提供**，请自行用 `keytool` 生成。

## 许可与合规

- Winlator 11.2.0：**LGPL-2.1**，[应用源码](https://github.com/brunodev85/winlator-app)；完整许可文本见 [`LICENSE-LGPL-2.1.txt`](LICENSE-LGPL-2.1.txt)。
- Wine / Wine Mono：LGPL-2.1；Box86/Box64：MIT；PRoot：GPL-2.0；Mesa / DXVK / VKD3D / commons-compress 等见 [`NOTICE.txt`](NOTICE.txt)。
- 本仓库提供全部改造脚本、中文词表与许可证声明；依据 LGPL-2.1 第 6 条，二进制所用库的完整源码可从上述上游官方仓库获取。
- 第三方程序及其数据版权归各自权利人；本仓库不含任何授权，请勿随包分发受版权保护的数据。

## 已知限制

- 开发环境无安卓真机，**尚未做真机启动验证**；示例快捷方式能否拉起 32 位 x86 程序取决于具体 exe 与 Wine/Box64 兼容性。
- 点击启动项黑屏后退回：按 01→05 顺序逐个试，并保留 Wine 错误弹窗内容用于排障（不要加 `-nonotify`）。
- 自签名 APK，Android 会提示「未知来源」；更换签名后旧容器数据无法直接沿用。

## 文件说明

| 文件 | 用途 |
|---|---|
| `scripts/patch_apk.py` | 核心改造：资源、中文、容器模板、回编译、对齐、签名 |
| `scripts/zh_strings.py` | 401 条中文界面词表 |
| `scripts/verify_apk.py` | 离线质量校验（不依赖安卓设备） |
| `scripts/prepare_game.py` | 本地游戏文件精简（仅个人自用，产物不上传） |
| `docs/示例-启动方案说明.html` | 5 个启动方案的完整参数与排障说明 |
| `scripts/publish_github.py` | 幂等发布脚本（推文件 / 建 Release / 传 APK），token 只从环境变量读取 |
| `RELEASE_NOTES.md` | Release 发布正文 |
| `构建报告.json` / `校验报告.json` | 本次构建的摘要与校验结果 |
