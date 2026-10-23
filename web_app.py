#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地网页控制台：在浏览器中管理学信网照片替换代理。"""

from __future__ import annotations

import argparse
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import idphoto_wg_qr


SOURCE_ROOT = Path(__file__).resolve().parent
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SOURCE_ROOT
WEB_DIR = BUNDLE_ROOT / "web"
PLUGIN_FILE = BUNDLE_ROOT / "mitm_replace_photo.py"
RUNTIME_DIR = ROOT / ".runtime"
UPLOAD_DIR = RUNTIME_DIR / "uploads"
LOG_FILE = RUNTIME_DIR / "idphoto_replace.log"
QR_FILE = ROOT / "wg-client-qr.png"
CONF_FILE = ROOT / "wg-client.conf"
MIN_SIZE = 1024
MAX_SIZE = 1048576
MAX_REQUEST_SIZE = 20 * 1024 * 1024
LAN_NETWORKS = tuple(ipaddress.IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def is_lan_ip(ip: str) -> bool:
    return any(ipaddress.IPv4Address(ip) in network for network in LAN_NETWORKS)


def windows_lan_candidates(output: str) -> list[str]:
    """ipconfig (without /all) lists address, netmask and gateway per adapter."""
    candidates = []
    for block in re.split(r"\r?\n(?=\S)", output):
        match = re.search(r"IPv4[^\r\n]*?(\d{1,3}(?:\.\d{1,3}){3})", block)
        if not match or not is_lan_ip(match.group(1)):
            continue
        address = match.group(1)
        # A private gateway distinguishes LAN interfaces from WSL/Hyper-V.
        other_ips = re.findall(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])", block[match.end():])
        if any(ip != address and is_lan_ip(ip) for ip in other_ips):
            candidates.append(address)
    return candidates


def private_local_ip() -> str:
    """返回当前机器可被同一局域网手机访问的 IPv4 地址。"""
    candidates = []
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["ipconfig"], capture_output=True, text=True, errors="replace", timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            candidates.extend(windows_lan_candidates(result.stdout))
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            candidates.append(ip)
    except OSError:
        pass
    try:
        candidates.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    # Clash 的 198.18.x.x 是虚拟网卡地址，手机无法用它访问电脑。
    for ip in candidates:
        if is_lan_ip(ip):
            return ip
    return ""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_mitm_command(ip: str, port: int) -> list[str]:
    return choose_mitm_command() + [
        "-m", f"wireguard@{ip}:{port}",
        "-s", str(PLUGIN_FILE),
        "--allow-hosts", r"chsi-idphotosrv\.oss-cn-shanghai\.aliyuncs\.com",
        "--set", "flow_detail=0",
        "--set", "termlog_verbosity=warn",
    ]


class LocalHTTPServer(ThreadingHTTPServer):
    """Avoid accidental port sharing on Windows."""

    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class RuntimeState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.process: subprocess.Popen[str] | None = None
        self.photo_path: Path | None = None
        self.photo_name = ""
        self.photo_size = 0
        self.photo_md5 = ""
        self.ip = private_local_ip()
        self.port = 51820
        self.mode = "wireguard"
        self.logs: deque[str] = deque(maxlen=500)
        self.error = ""
        self.qr_ready = False
        self.config_text = ""

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def add_log(self, line: str) -> None:
        line = line.rstrip("\r\n")
        if line:
            with self.lock:
                self.logs.append(line)


STATE = RuntimeState()


def parse_multipart(content_type: str, body: bytes) -> tuple[str, bytes]:
    """解析网页上传的单文件 multipart 请求，不依赖第三方 Web 框架。"""
    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;\s]+))", content_type, re.I)
    if not match:
        raise ValueError("上传请求缺少 multipart boundary")
    boundary = (match.group(1) or match.group(2)).encode("latin-1")
    delimiter = b"--" + boundary
    for part in body.split(delimiter):
        if not part or part.startswith(b"--"):
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if b"\r\n\r\n" not in part:
            continue
        raw_headers, data = part.split(b"\r\n\r\n", 1)
        # 只移除 multipart 分隔符前的那一对 CRLF，不能用 strip，
        # 否则会误删图片真实内容末尾可能存在的换行字节。
        headers = raw_headers.decode("latin-1", errors="replace")
        disposition = next(
            (line for line in headers.split("\r\n")
             if line.lower().startswith("content-disposition:")), ""
        )
        name_match = re.search(r"name\s*=\s*[\"']?([^;\"'\s]+)", disposition, re.I)
        if not name_match or name_match.group(1) != "photo":
            continue
        filename_match = re.search(r"filename\s*=\s*[\"']?([^;\"']*)", disposition, re.I)
        filename = filename_match.group(1) if filename_match else "photo.jpg"
        return Path(filename).name or "photo.jpg", data
    raise ValueError("没有找到名为 photo 的图片字段")


def md5_hex(data: bytes) -> str:
    import hashlib
    return hashlib.md5(data).hexdigest()


def choose_mitm_command() -> list[str]:
    """优先使用 mitmdump，找不到时使用当前 Python 的 mitmproxy 模块。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--mitmdump"]
    candidates = [
        ROOT / ".venv" / "Scripts" / "mitmdump.exe",
        ROOT / ".venv" / "Scripts" / "mitmdump",
    ]
    which = shutil.which("mitmdump")
    if which:
        candidates.insert(0, Path(which))
    for candidate in candidates:
        if candidate.exists():
            return [str(candidate)]
    try:
        import importlib.util
        if importlib.util.find_spec("mitmproxy"):
            # mitmdump 的 console entry point 是 main:mitmdump；
            # tools.dump 只是实现类，直接用 -m 会导入后立即退出。
            return [sys.executable, "-c", "from mitmproxy.tools.main import mitmdump; mitmdump()"]
    except Exception:
        pass
    raise RuntimeError(
        "找不到 mitmdump。请先运行启动脚本安装依赖，或在当前 Python 环境执行 pip install -r requirements.txt"
    )


def terminate_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def monitor_process(process: subprocess.Popen[str]) -> None:
    try:
        assert process.stdout is not None
        for line in process.stdout:
            STATE.add_log(line)
    except Exception as exc:
        STATE.add_log(f"✖ 读取代理输出失败：{exc}")
    finally:
        code = process.wait()
        with STATE.lock:
            if STATE.process is process:
                STATE.process = None
                clear_phone_config()
        if code != 0:
            STATE.add_log(f"✖ 代理进程已退出，返回码 {code}")
        else:
            STATE.add_log("代理已停止")


def clear_phone_config() -> None:
    """Called under STATE.lock so stop/restart cannot publish a stale link."""
    STATE.qr_ready = False
    STATE.config_text = ""


def generate_qr_when_ready(ip: str, port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and process.poll() is None:
        if Path(idphoto_wg_qr.WG_CONF).exists():
            try:
                with STATE.lock:
                    if STATE.process is not process or process.poll() is not None:
                        return
                    qr_ok = idphoto_wg_qr.generate_client_config(
                        ip, str(port), str(CONF_FILE), str(QR_FILE)
                    )
                    STATE.qr_ready = qr_ok and QR_FILE.exists()
                    STATE.config_text = read_text(CONF_FILE)
                STATE.add_log("✓ 手机配置已生成" + ("，二维码可扫码导入" if qr_ok else "，当前只有配置文本"))
            except Exception as exc:
                STATE.add_log(f"⚠ 生成手机配置失败：{exc}")
            return
        time.sleep(0.25)
    if STATE.process is process and process.poll() is None:
        STATE.add_log("⚠ 等待 mitmproxy 生成 WireGuard 密钥超时，请查看日志")


def start_proxy(ip: str, port: int = 51820) -> None:
    if STATE.running():
        raise RuntimeError("代理已经在运行")
    if not STATE.photo_path or not STATE.photo_path.exists():
        raise RuntimeError("请先选择证件照")
    if not MIN_SIZE <= STATE.photo_size <= MAX_SIZE:
        raise RuntimeError(f"图片大小必须在 1KB~1MB，当前为 {STATE.photo_size} 字节")
    try:
        address = ipaddress.IPv4Address(ip)
        if address.is_loopback or address.is_unspecified or address.is_multicast or address in ipaddress.IPv4Network("198.18.0.0/15"):
            raise ValueError()
    except ValueError:
        raise RuntimeError("请填写手机能访问的电脑局域网 IPv4 地址，例如 192.168.1.9")
    if not 1 <= port <= 65535:
        raise RuntimeError("端口必须在 1~65535 之间")
    RUNTIME_DIR.mkdir(exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")
    STATE.ip, STATE.port, STATE.mode = ip, port, "wireguard"
    STATE.error = ""
    clear_phone_config()
    CONF_FILE.unlink(missing_ok=True)
    QR_FILE.unlink(missing_ok=True)

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    command = build_mitm_command(ip, port)
    env = os.environ.copy()
    env["IDPHOTO_FILE"] = str(STATE.photo_path)
    env["IDPHOTO_LOG_FILE"] = str(LOG_FILE)
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
    )
    with STATE.lock:
        STATE.process = process
        STATE.logs.clear()
    threading.Thread(target=monitor_process, args=(process,), daemon=True).start()
    threading.Thread(target=generate_qr_when_ready, args=(ip, port, process), daemon=True).start()
    STATE.add_log(f"▶ 正在启动 WireGuard 代理：{ip}:{port}")


def stop_proxy() -> None:
    with STATE.lock:
        process = STATE.process
        # Invalidate any pending configuration generation before stopping.
        STATE.process = None
        clear_phone_config()
    if process is None:
        return
    terminate_process(process)
    STATE.add_log("✓ 已停止 WireGuard 代理；请关闭手机上的隧道")


def json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    server_version = "IdPhotoWeb/1.0"

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            with STATE.lock:
                payload = {
                    "running": STATE.running(),
                    "photo": {
                        "name": STATE.photo_name,
                        "size": STATE.photo_size,
                        "md5": STATE.photo_md5,
                    } if STATE.photo_path else None,
                    "ip": STATE.ip,
                    "port": STATE.port,
                    "mode": STATE.mode,
                    "qrReady": STATE.qr_ready,
                    "config": STATE.config_text,
                    "logs": list(STATE.logs)[-300:],
                    "error": STATE.error,
                }
            json_response(self, payload)
            return
        if parsed.path == "/api/qr":
            if not STATE.qr_ready or not QR_FILE.exists():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            data = QR_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        self.serve_static(parsed.path)

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_DIR / relative).resolve()
        if WEB_DIR.resolve() not in target.parents:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/photo":
            self.upload_photo()
            return
        if parsed.path == "/api/start":
            self.start_request()
            return
        if parsed.path == "/api/stop":
            try:
                stop_proxy()
                json_response(self, {"ok": True})
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, 500)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def request_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("请求体大小无效")
        if length <= 0 or length > MAX_REQUEST_SIZE:
            raise ValueError("上传请求过大，最多支持 20MB")
        return self.rfile.read(length)

    def upload_photo(self) -> None:
        try:
            body = self.request_body()
            filename, data = parse_multipart(self.headers.get("Content-Type", ""), body)
            if not data:
                raise ValueError("图片内容为空")
            if len(data) < MIN_SIZE or len(data) > MAX_SIZE:
                raise ValueError(f"图片大小必须在 1KB~1MB，当前为 {len(data)} 字节。请让网页自动压缩后再试")
            if not re.search(r"\.(jpe?g|png|webp)$", filename, re.I):
                raise ValueError("只支持 JPG、PNG、WEBP 图片")
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            path = UPLOAD_DIR / ("selected" + Path(filename).suffix.lower())
            path.write_bytes(data)
            with STATE.lock:
                STATE.photo_path = path
                STATE.photo_name = filename
                STATE.photo_size = len(data)
                STATE.photo_md5 = md5_hex(data)
                STATE.error = ""
            STATE.add_log(f"✓ 已载入 {filename}（{len(data)} 字节，MD5 {STATE.photo_md5}）")
            json_response(self, {"ok": True, "name": filename, "size": len(data), "md5": STATE.photo_md5})
        except Exception as exc:
            with STATE.lock:
                # 重复点击“启动”应由本次响应提示，不要覆盖正在运行实例的全局状态。
                if not STATE.running():
                    STATE.error = str(exc)
            json_response(self, {"ok": False, "error": str(exc)}, 400)

    def start_request(self) -> None:
        try:
            body = self.request_body()
            data = json.loads(body.decode("utf-8")) if body else {}
            ip = str(data.get("ip") or STATE.ip or private_local_ip()).strip()
            port = int(data.get("port") or STATE.port)
            with STATE.lock:
                start_proxy(ip, port)
            json_response(self, {"ok": True})
        except Exception as exc:
            with STATE.lock:
                STATE.error = str(exc)
            json_response(self, {"ok": False, "error": str(exc)}, 400)


def main() -> int:
    parser = argparse.ArgumentParser(description="学信网照片替换本地网页控制台")
    parser.add_argument("--host", default="127.0.0.1", help="网页监听地址")
    parser.add_argument("--port", type=int, default=8765, help="网页监听端口")
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    RUNTIME_DIR.mkdir(exist_ok=True)
    server = LocalHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"本地网页控制台：{url}")
    print("按 Ctrl+C 停止网页服务；退出前会尝试停止代理。")
    if getattr(sys, "frozen", False) and not args.no_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_proxy()
        server.server_close()
    return 0


def entrypoint() -> int:
    if "--mitmdump" in sys.argv[1:]:
        sys.argv.remove("--mitmdump")
        from mitmproxy.tools.main import mitmdump
        mitmdump()
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(entrypoint())
