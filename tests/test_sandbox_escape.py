"""Adversarial escape tests: try known namespace-sandbox escape vectors.

Each probe runs a real command inside the sandbox and must be refused by the
kernel. Skipped when no OS sandbox backend is available.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from babymind import runner, sandbox


@unittest.skipUnless(sandbox.available(), "no OS sandbox backend in this environment")
class SandboxEscapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "work").mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def probe(self, code: str) -> dict:
        return runner.run_command(
            [sys.executable, "-c", code],
            cwd=self.root / "work", allowed_root=self.root, timeout=60, sandbox="require",
        )

    def test_system_binaries_are_read_only(self):
        result = self.probe(
            "try:\n"
            "    open('/usr/bin/env', 'w').write('x'); print('WRITABLE')\n"
            "except OSError:\n"
            "    print('BLOCKED')\n"
        )
        self.assertIn("BLOCKED", result["stdout"], result)

    def test_host_files_outside_chroot_are_not_reachable_via_proc(self):
        with TemporaryDirectory() as outside:
            secret = Path(outside) / "host-secret.txt"
            secret.write_text("host secret")
            result = self.probe(
                f"import os\n"
                f"for p in ('{secret}', '/proc/1/root{secret}'):\n"
                "    try:\n"
                "        open(p).read(); print('READABLE', p)\n"
                "    except OSError:\n"
                "        print('BLOCKED', p)\n"
            )
        self.assertIn("BLOCKED", result["stdout"], result)
        self.assertNotIn("host secret", result["stdout"], result)

    def test_host_shadow_is_not_readable(self):
        result = self.probe(
            "try:\n"
            "    open('/etc/shadow').read(); print('READABLE')\n"
            "except OSError:\n"
            "    print('BLOCKED')\n"
        )
        self.assertIn("BLOCKED", result["stdout"], result)

    def test_system_paths_are_not_writable(self):
        result = self.probe(
            "try:\n"
            "    open('/sys/kernel/uevent_helper', 'w').write('x'); print('WRITABLE')\n"
            "except OSError:\n"
            "    print('BLOCKED')\n"
        )
        self.assertIn("BLOCKED", result["stdout"], result)

    def test_host_processes_are_not_visible_or_attachable(self):
        # Host pids do not exist in the sandbox PID namespace; attaching to a
        # host-range pid number must fail.
        result = self.probe(
            "import ctypes\n"
            "libc = ctypes.CDLL(None, use_errno=True)\n"
            "r = libc.ptrace(16, 30000, 0, 0)  # PTRACE_ATTACH to a host-range pid\n"
            "print('ESCAPED' if r == 0 else 'BLOCKED')\n"
        )
        self.assertIn("BLOCKED", result["stdout"], result)

    def test_unix_socket_to_host_is_refused(self):
        result = self.probe(
            "import socket\n"
            "try:\n"
            "    s = socket.socket(socket.AF_UNIX)\n"
            "    s.connect('/var/run/docker.sock'); print('ESCAPED')\n"
            "except OSError:\n"
            "    print('BLOCKED')\n"
        )
        self.assertIn("BLOCKED", result["stdout"], result)

    def test_in_namespace_root_has_no_power_over_host_files(self):
        # Inside a user namespace we are uid 0 *in-namespace*; that must not
        # grant access to host files outside the chroot.
        with TemporaryDirectory() as outside:
            secret = Path(outside) / "shadow-like.txt"
            secret.write_text("root:hash")
            result = self.probe(
                "import os\n"
                "assert os.getuid() == 0\n"
                f"try:\n    open({str(secret)!r}).read(); print('ESCAPED')\n"
                "except OSError:\n    print('BLOCKED')\n"
            )
        self.assertIn("BLOCKED", result["stdout"], result)

    def test_kernel_module_load_is_refused(self):
        result = self.probe(
            "import ctypes\n"
            "libc = ctypes.CDLL(None, use_errno=True)\n"
            "r = libc.init_module(b'', 0, b'')\n"
            "print('LOADED' if r == 0 else 'BLOCKED')\n"
        )
        self.assertIn("BLOCKED", result["stdout"], result)

    def test_network_namespace_blocks_external_connect(self):
        result = self.probe(
            "import socket\n"
            "s = socket.socket(); s.settimeout(3)\n"
            "try:\n"
            "    s.connect(('1.1.1.1', 53)); print('ESCAPED')\n"
            "except OSError:\n"
            "    print('BLOCKED')\n"
        )
        self.assertIn("BLOCKED", result["stdout"], result)


class NestedSandboxTests(unittest.TestCase):
    def test_nested_detection_returns_bool(self):
        self.assertIsInstance(sandbox.nested_sandbox_detected(), bool)

    def test_status_reports_nesting(self):
        report = sandbox.status()
        self.assertIn("nested_sandbox_detected", report)


if __name__ == "__main__":
    unittest.main()
