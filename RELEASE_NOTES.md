## exetoapk安卓wine模拟器汉化 · v1.0

基于 Winlator 11.2.0 的安卓 Wine/Box64 兼容层全中文定制版（轻量版）。

- 应用名：`exetoapk安卓wine模拟器汉化`
- 文件：`exetoapk安卓wine模拟器汉化.apk`（153.8 MB）
- SHA-256：`32d51edee1f980a7952fdd875dbb48d44acc26ef90a680a7a8e0f37ee136d1ef`
- 签名：自签名 v2 + v3（与官方 Winlator 同包名，不能共存，需先卸载官方版）
- 内含：Wine/Box64 运行时、401 条中文界面词表、容器模板修复、5 个示例快捷方式
- **不含**：任何游戏 / 商业软件数据、EXE、DLL、MPQ、CD-KEY

### 使用
1. 安装后首次打开，先到「容器」页点右上角 + 新建容器，等待解压完成。
2. 回到「快捷方式」页可见 5 个示例启动项（仅为路径示例，指向 `D://DiabloII`）。
3. 容器建议：Box64 = Stability，图形驱动 VirGL，DX Wrapper = wined3d，分辨率 800x600。
4. 要运行自己的 exe，请把程序放进手机 `Download/DiabloII/`，或按需修改快捷方式 Exec 路径。

### 合规
Winlator 11.2.0 采用 LGPL-2.1，本仓库提供全部改造脚本、中文词表与完整许可证声明，
上游源码地址见 `NOTICE.txt` / `README.md`。第三方程序版权归各自权利人，请勿随包分发受版权保护的数据。

> 名称中的 wine 指 Wine 兼容层。开发环境无安卓真机，尚未做真机启动验证。
