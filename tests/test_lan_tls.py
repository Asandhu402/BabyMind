"""Tests for trusted HTTPS LAN mode."""
from __future__ import annotations

import ssl
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from babymind.lan_tls import create_lan_tls_context


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"BabyMind TLS OK"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        pass


class LanTlsTests(unittest.TestCase):
    def test_tls_server_uses_a_trusted_certificate_and_persists_ca(self) -> None:
        with TemporaryDirectory() as folder:
            context, ca_path = create_lan_tls_context(folder, "127.0.0.1")
            original_ca = ca_path.read_bytes()
            sealed_key = Path(folder) / "certs" / "lan-ca-private.pem.enc"
            self.assertTrue(sealed_key.is_file())
            self.assertTrue(sealed_key.read_text(encoding="ascii").startswith("bmenc:v1:"))
            self.assertNotIn(b"PRIVATE KEY", sealed_key.read_bytes())

            server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client_context = ssl.create_default_context(cafile=str(ca_path))
                with urlopen(
                    f"https://127.0.0.1:{server.server_port}/health",
                    context=client_context,
                    timeout=3,
                ) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), b"BabyMind TLS OK")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

            _, second_ca_path = create_lan_tls_context(folder, "127.0.0.1")
            self.assertEqual(second_ca_path.read_bytes(), original_ca)

    def test_certificate_file_is_written_for_lan_trust_setup(self) -> None:
        with TemporaryDirectory() as folder:
            _, ca_path = create_lan_tls_context(folder, "192.0.2.44")
            self.assertTrue(ca_path.is_file())
            self.assertIn(b"BEGIN CERTIFICATE", ca_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
