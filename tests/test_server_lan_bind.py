"""Regression tests for the secure LAN server bind address."""
from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from babymind import server


class LanBindTests(unittest.TestCase):
    def test_lan_mode_binds_to_detected_private_interface_address(self) -> None:
        args = argparse.Namespace(
            lan=True, host="127.0.0.1", port=8765, no_browser=True
        )
        probe = Mock()
        probe.getsockname.return_value = ("192.168.1.42", 0)
        http_server = Mock()
        http_server.serve_forever.side_effect = KeyboardInterrupt

        with (
            patch.object(server.argparse.ArgumentParser, "parse_args", return_value=args),
            patch.object(server, "init_db"),
            patch.object(server.socket, "socket", return_value=probe),
            patch.object(
                server, "create_lan_tls_context",
                return_value=(None, Path("lan-ca.crt")),
            ),
            patch.object(server, "ThreadingHTTPServer", return_value=http_server) as factory,
            patch.object(server.secrets, "token_urlsafe", return_value="test-token"),
        ):
            server.main()

        probe.connect.assert_called_once_with(("192.0.2.1", 80))
        factory.assert_called_once_with(("192.168.1.42", 8765), server.Handler)
        self.assertEqual(http_server.auth_token, "test-token")
        http_server.server_close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
