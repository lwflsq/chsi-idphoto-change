# macOS 使用说明

安装运行依赖：

```bash
brew install mitmproxy python
python3 -m pip install segno
```

从 Finder 双击 `启动换图代理.command`，或在项目根目录执行：

```bash
chmod +x macos/*.command
./macos/启动换图代理.command
```

脚本会调用系统选图窗口，将图片处理到 1KB～1MB，生成 WireGuard 配置并启动 mitmproxy。

更换 Wi-Fi 或电脑局域网 IP 后，可以单独重新生成二维码：

```bash
./macos/生成隧道二维码.command
```

生成的 `wg-client.conf` 和 `wg-client-qr.png` 位于项目根目录。
