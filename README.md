# chsi-idphoto-change

在研招网 / 学信网 App 的“图像采集”流程中，将即将上传的现场照片替换为本地准备好的证件照。项目通过 mitmproxy 的 WireGuard 模式接收手机流量，并提供 Windows 网页控制台和 macOS 启动脚本。

> 本项目只应用于本人账号和本人照片。请勿冒用他人身份、伪造身份材料或规避实名核验。

## 平台入口

| 平台 | 推荐入口 | 说明 |
|---|---|---|
| Windows 10/11 x64 | [`windows/启动网页控制台.bat`](windows/启动网页控制台.bat) | 自动创建 Python 虚拟环境并打开本地网页 |
| Windows 免 Python 版 | `chsi-idphoto-swap-windows-x64.zip` | 由 [`windows/build_portable.ps1`](windows/build_portable.ps1) 生成，目标电脑无需安装 Python |
| macOS | [`macos/启动换图代理.command`](macos/启动换图代理.command) | 使用系统选图窗口和终端日志 |

Windows 说明见 [`windows/README.md`](windows/README.md)，macOS 说明见 [`macos/README.md`](macos/README.md)。

## 工作原理

App 会先向服务端申请上传凭据，最后通过 HTTPS 将图片以 OSS `PostObject` 表单上传。本项目在请求离开手机前替换 `multipart` 中的图片字段，保留服务端签发的其他参数。

上传完成后，插件会比较 OSS 返回的 ETag 与本地图片 MD5。二者一致时，日志会显示“服务端存的就是本地图”。完整技术分析见 [`原理与逆向分析.md`](原理与逆向分析.md)。

项目采用 fail-safe 处理：识别到目标上传请求但无法完成替换时，会中断该次请求，避免现场照片被原样上传。

## 使用前准备

- 手机与电脑处于同一个可互访的局域网。
- 手机安装 WireGuard 客户端。
- 准备 JPG、PNG 或 WEBP 图片，网页会将其处理到 1KB～1MB。
- 手机信任运行代理的电脑生成的 mitmproxy CA，具体见下方“HTTPS 证书”。

## Windows 快速开始

### 使用源码运行

1. 安装 Python 3.12 或更高版本，并勾选 **Add Python to PATH**。
2. 下载并完整解压本仓库。
3. 双击 [`windows/启动网页控制台.bat`](windows/启动网页控制台.bat)。
4. 首次启动会在项目根目录创建 `.venv` 并安装依赖。
5. 浏览器打开 `http://127.0.0.1:8765` 后，选择照片并点击“启动 WireGuard”。
6. 使用手机 WireGuard 扫描网页二维码并打开隧道。
7. 回到学信网 App，正常执行拍照和上传流程。
8. App 显示最终照片并完成确认后，在网页停止代理，再关闭手机 WireGuard。

也可以在 PowerShell 中手动运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe web_app.py
```

### 构建免 Python 便携版

先运行一次 Windows 启动器以创建 `.venv`，然后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build_portable.ps1
```

构建结果位于：

```text
dist/chsi-idphoto-swap-windows-x64.zip
```

便携版必须完整解压后运行，不能只复制其中的 EXE，也不要直接在压缩包内双击。

## macOS 快速开始

先安装依赖：

```bash
brew install mitmproxy python
python3 -m pip install segno
```

然后从 Finder 双击 [`macos/启动换图代理.command`](macos/启动换图代理.command)，或在终端执行：

```bash
chmod +x macos/*.command
./macos/启动换图代理.command
```

脚本会选择照片、处理图片、生成 WireGuard 配置并启动代理。网络地址变化时，可单独运行 [`macos/生成隧道二维码.command`](macos/生成隧道二维码.command)。

## HTTPS 证书

照片上传目标使用 HTTPS。WireGuard 已握手、普通网站能够联网，只能说明隧道可用；如果手机不信任当前电脑的 mitmproxy CA，目标上传步骤仍可能提示无网络。

首次启动代理后，mitmproxy 会生成以下目录：

| 平台 | CA 与密钥目录 |
|---|---|
| Windows | `%USERPROFILE%\.mitmproxy` |
| macOS | `~/.mitmproxy` |

需要传到手机的证书文件是 `mitmproxy-ca-cert.cer`。部分 Android App 不接受普通“用户证书”，已 root 的设备通常需要按所用证书模块的说明将其加入系统信任区。

从一台已经可以使用的电脑迁移时，也可以在程序完全退出后，将旧电脑的整个 `.mitmproxy` 目录复制到新电脑的同一位置。随后仍应重新生成或扫描二维码，因为电脑局域网 IP 可能已经变化。

`mitmproxy-ca.pem` 包含 CA 私钥，`wireguard.conf` 包含隧道私钥。它们只能保存在自己的可信设备上，不要公开上传或分享。

## 成功日志

网页或终端会依次出现类似日志：

| 日志 | 含义 |
|---|---|
| `✓ 照片替换插件已加载` | 插件文件已经成功载入 |
| `✓ WireGuard 代理核心已就绪` | UDP 监听和代理核心已启动 |
| `✓ 隧道已收到手机流量` | 手机流量已经进入代理 |
| `⇢ POST chsi-idphotosrv.oss...` | 捕获到目标上传请求 |
| `✔ 已替换 xxx.jpg` | 请求中的图片已替换 |
| `🎉 上传成功 —— OSS 返回 201` | OSS 已接收上传 |
| `🔒 服务端存的就是本地图` | ETag 与本地 MD5 一致 |
| `✖ 已拦截本次上传` | 替换失败，请求已被安全中断 |

必须等 App 显示照片并完成后续确认，再停止代理。代理进程同时也是手机的 WireGuard 网关，提前停止会让手机暂时断网。

## 常见问题

### WireGuard 有握手，但上传时提示无网络

优先查看网页日志是否出现 TLS / certificate 错误。旧电脑可用、新电脑不可用时，通常是手机只信任旧电脑的 CA。迁移旧 `.mitmproxy` 目录，或让手机信任新电脑生成的 CA。

### 手机无法连接电脑

- 检查网页中的 IP 是否为电脑当前局域网地址，例如 `192.168.x.x`。
- Windows 防火墙弹窗中允许程序访问“专用网络”。
- 公共 Wi-Fi、企业 Wi-Fi 可能启用客户端隔离，需要更换网络。
- 更换电脑或网络后，重新扫描二维码。

### 开启 WireGuard 后手机所有流量都经过电脑

客户端配置使用 `AllowedIPs = 0.0.0.0/0`，这是预期行为。目标照片上传请求会被修改，其他流量由代理转发。流程结束后关闭手机 WireGuard。

### 使用手机热点后出现断网

如果手机既给电脑提供网络，又通过这台电脑作为 WireGuard 网关，可能形成网络环路。让电脑使用另一条独立网络，或改用其他设备提供热点。

### Windows 网页打不开

默认网页地址是 `http://127.0.0.1:8765`。端口被占用时可以运行：

```powershell
.\windows\启动网页控制台.ps1 -Port 8766
```

## 目录结构

```text
├─ windows/                   Windows 启动器、便携版构建脚本和随包说明
├─ macos/                     macOS 启动器和二维码辅助脚本
├─ web/                       本地网页界面
├─ tests/                     核心逻辑测试
├─ web_app.py                 网页服务和代理进程管理
├─ mitm_replace_photo.py      mitmproxy 图片替换插件
├─ idphoto_wg_qr.py           WireGuard 客户端配置与二维码生成
├─ chsi_idphoto_tool.py       协议分析辅助工具
├─ requirements.txt           Python 依赖
└─ 原理与逆向分析.md          技术原理与逆向记录
```

运行时生成的照片、日志、WireGuard 配置和二维码已加入 `.gitignore`，不会随源码提交。
