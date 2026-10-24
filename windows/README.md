# Windows 使用说明

## 源码启动

安装 Python 3.12 或更高版本后，双击 `启动网页控制台.bat`。脚本会在项目根目录创建 `.venv`、安装依赖并打开 `http://127.0.0.1:8765`。

检查环境但不启动网页：

```powershell
.\windows\启动网页控制台.ps1 -Check
```

更换网页端口：

```powershell
.\windows\启动网页控制台.ps1 -Port 8766
```

## 构建便携版

先运行一次启动器创建 `.venv`，再从项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build_portable.ps1
```

输出文件为 `dist/chsi-idphoto-swap-windows-x64.zip`。压缩包内已包含 Python、mitmproxy 和网页资源。

`PORTABLE_README.txt` 是构建时复制进发布包的用户说明。
