import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlparse

import web_app


KEY = base64.b64encode(bytes(range(32))).decode()


def request(url, method="GET", body=None, headers=None):
    parsed = urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
    try:
        connection.request(method, parsed.path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


class ConsoleLifecycleTests(unittest.TestCase):
    def setUp(self):
        web_app.RUNTIME_DIR.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=web_app.RUNTIME_DIR)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        keys = root / "keys.json"
        keys.write_text(json.dumps({"client_key": KEY, "server_key": KEY}), encoding="utf-8")
        with patch.object(web_app, "private_local_ip", return_value="127.0.0.1"):
            self.state = web_app.RuntimeState()
        self.process = Mock()
        self.process.poll.return_value = None
        self.process.wait.return_value = 0
        self.state.process = self.process
        for target, attribute, value in (
            (web_app, "STATE", self.state),
            (web_app, "RUNTIME_DIR", root),
            (web_app, "CONF_FILE", root / "wg-client.conf"),
            (web_app, "QR_FILE", root / "wg-qr.png"),
            (web_app.idphoto_wg_qr, "WG_CONF", str(keys)),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(web_app.stop_proxy)
        self.console = web_app.LocalHTTPServer(("127.0.0.1", 0), web_app.Handler)
        self.thread = threading.Thread(target=self.console.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_console)
        self.base = f"http://127.0.0.1:{self.console.server_port}"

    def close_console(self):
        self.console.shutdown()
        self.console.server_close()
        self.thread.join(timeout=2)

    def test_generation_and_stop(self):
        web_app.generate_qr_when_ready("127.0.0.1", 51820, self.process)
        status = json.loads(request(self.base + "/api/status")[2])
        self.assertTrue(status["qrReady"])
        self.assertIn("[Interface]", status["config"])
        self.assertEqual(status["mode"], "wireguard")
        for removed in ("clashUrl", "rootUri", "vmessUri", "gatewayRunning"):
            self.assertNotIn(removed, status)
        self.assertEqual(request(self.base + "/api/qr")[0], 200)

        self.assertEqual(request(self.base + "/api/stop", "POST")[0], 200)
        self.process.terminate.assert_called_once()
        stopped = json.loads(request(self.base + "/api/status")[2])
        self.assertFalse(stopped["qrReady"])
        self.assertEqual(stopped["config"], "")
        self.assertEqual(request(self.base + "/api/qr")[0], 404)

    def test_unexpected_proxy_exit_revokes_config(self):
        web_app.generate_qr_when_ready("127.0.0.1", 51820, self.process)
        self.process.stdout = []
        self.process.wait.return_value = 1
        web_app.monitor_process(self.process)
        self.assertFalse(self.state.qr_ready)
        self.assertEqual(self.state.config_text, "")


class AddressTests(unittest.TestCase):
    def test_virtual_adapters_are_not_selected(self):
        output = """
Unknown adapter FlClash:
   IPv4 Address: 198.18.0.1
   Subnet Mask: 255.255.255.252
   Default Gateway: 198.18.0.2
Ethernet adapter vEthernet (WSL):
   IPv4 Address: 172.29.128.1
   Subnet Mask: 255.255.240.0
   Default Gateway:
Ethernet adapter LAN:
   IPv4 Address: 192.168.1.9
   Subnet Mask: 255.255.255.0
   Default Gateway: fe80::1%11
                    192.168.1.1
"""
        self.assertEqual(web_app.windows_lan_candidates(output), ["192.168.1.9"])


class WireGuardTests(unittest.TestCase):
    def test_wireguard_is_the_only_command(self):
        with patch.object(web_app, "choose_mitm_command", return_value=["mitmdump"]):
            command = web_app.build_mitm_command("192.168.1.9", 51820)
        self.assertEqual(command[1:3], ["-m", "wireguard@192.168.1.9:51820"])
        self.assertIn(str(web_app.PLUGIN_FILE), command)

    def test_defaults_are_wireguard(self):
        with patch.object(web_app, "private_local_ip", return_value="192.168.1.9"):
            state = web_app.RuntimeState()
        self.assertEqual(state.mode, "wireguard")
        self.assertEqual(state.port, 51820)


if __name__ == "__main__":
    unittest.main()
