"""Tests for the OS sandbox.

These tests run real processes inside real namespaces. They are skipped when the
platform cannot provide a backend, and every assertion is about observed
behaviour, not configuration.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from babymind import runner, sandbox

AVAILABLE = sandbox.available()
SKIP_REASON = sandbox.backend().detail


class SandboxDetectionTests(unittest.TestCase):
    def test_status_reports_mechanisms_or_says_it_cannot(self) -> None:
        report = sandbox.status()
        self.assertIn("backend", report)
        self.assertIn("mechanisms", report)
        if not report["available"]:
            self.assertTrue(report["detail"])
            self.assertIn("not enforced", report["mechanisms"]["network"])

    def test_tmp_interpreter_prefix_is_not_a_writable_bind(self) -> None:
        with patch.object(sandbox.sys, "prefix", "/tmp/test-python-env"), \
             patch.object(sandbox.sys, "base_prefix", "/usr"):
            readonly, temp_readonly = sandbox._interpreter_binds()
        self.assertEqual(temp_readonly, ["/tmp/test-python-env"])
        self.assertNotIn("/tmp/test-python-env", readonly)

    def test_self_test_uses_existing_outside_marker_and_requires_success(self) -> None:
        with TemporaryDirectory() as project:
            calls = []
            def fake_run(argv, **kwargs):
                calls.append(argv[-1])
                if len(calls) == 1:
                    return {"ok": False, "exit_code": 1,
                            "stdout": "NAMESPACE_ISOLATED BLOCKED", "stderr": ""}
                if len(calls) == 2:
                    marker = Path(ast.literal_eval(argv[-1].splitlines()[0].split("=", 1)[1].strip()))
                    self.assertTrue(marker.is_file())
                    self.assertFalse(marker.is_relative_to(Path(project)))
                    return {"ok": True, "exit_code": 0, "stdout": "BLOCKED", "stderr": ""}
                return {"ok": True, "exit_code": 0,
                        "stdout": "BLOCKED" if len(calls) == 3 else "WRITABLE", "stderr": ""}
            with patch.object(sandbox, "backend", return_value=sandbox.Backend("fixture", True, "fixture")), \
                 patch.object(runner, "run_command", side_effect=fake_run):
                evidence = sandbox.self_test(project)
            self.assertEqual(len(calls), 4)
            self.assertFalse(evidence["verified"])

    def test_other_platforms_are_not_supported(self) -> None:
        with patch("babymind.sandbox.sys.platform", "other"):
            record = sandbox.backend()
        self.assertFalse(record.available)
        self.assertIn("Only Linux", record.detail)


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class SandboxBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_in_sandbox(self, code: str, timeout: int = 60) -> dict:
        return runner.run_command(
            [sys.executable, "-c", code],
            cwd=self.root, allowed_root=self.root, timeout=timeout, sandbox="require",
        )

    def test_selftest_proves_every_part_of_the_boundary(self) -> None:
        evidence = sandbox.self_test(self.root)
        self.assertTrue(evidence["verified"], evidence)
        self.assertIn("BLOCKED", evidence["checks"]["network"]["output"])
        self.assertIn("NAMESPACE_ISOLATED", evidence["checks"]["network"]["output"])
        self.assertTrue(all(check["ok"] for check in evidence["checks"].values()))
        self.assertIn("BLOCKED", evidence["checks"]["host_secret"]["output"])
        self.assertIn("BLOCKED", evidence["checks"]["system_write"]["output"])
        self.assertIn("WRITABLE", evidence["checks"]["workspace_write"]["output"])

    def test_network_is_blocked(self) -> None:
        result = self.run_in_sandbox(
            "import socket\n"
            "s = socket.socket(); s.settimeout(3)\n"
            "try:\n"
            "    s.connect(('1.1.1.1', 53)); print('REACHABLE')\n"
            "except OSError as e:\n"
            "    print('BLOCKED', type(e).__name__)\n"
        )
        self.assertIn("BLOCKED", result["stdout"], result)

    def test_dns_is_blocked_too(self) -> None:
        result = self.run_in_sandbox(
            "import socket\n"
            "try:\n"
            "    print(socket.gethostbyname('example.com'))\n"
            "except OSError as e:\n"
            "    print('BLOCKED', type(e).__name__)\n"
        )
        self.assertIn("BLOCKED", result["stdout"], result)

    def test_host_secrets_outside_the_root_are_unreadable(self) -> None:
        with TemporaryDirectory() as outside:
            secret = Path(outside) / "secret.txt"
            secret.write_text("host secret")
            result = self.run_in_sandbox(
                f"target = {str(secret)!r}\n"
                "try:\n"
                "    open(target).read(); print('READABLE')\n"
                "except OSError:\n"
                "    print('BLOCKED')\n")
            self.assertTrue(result["ok"], result)
            self.assertIn("BLOCKED", result["stdout"], result)

    def test_tmp_interpreter_prefix_is_read_only(self) -> None:
        with TemporaryDirectory(prefix="babymind-test-venv-") as prefix:
            target = Path(prefix) / "sentinel"
            target.write_text("original")
            # Keep the real interpreter visible while simulating a second
            # interpreter prefix under /tmp outside the workspace.
            with patch.object(sandbox, "_interpreter_binds", return_value=([sys.prefix], [prefix])):
                result = self.run_in_sandbox(
                    f"p = {str(target)!r}\n"
                    "try:\n"
                    "    open(p, 'w').write('changed'); print('WROTE')\n"
                    "except OSError:\n"
                    "    print('BLOCKED')\n")
            self.assertTrue(result["ok"], result)
            self.assertIn("BLOCKED", result["stdout"], result)
            self.assertEqual(target.read_text(), "original")

    def test_system_paths_are_read_only(self) -> None:
        result = self.run_in_sandbox(
            "try:\n"
            "    open('/usr/bin/.babymind-probe', 'w').write('x'); print('WROTE')\n"
            "except OSError as e:\n"
            "    print('BLOCKED', type(e).__name__)\n"
        )
        self.assertIn("BLOCKED", result["stdout"], result)

    def test_workspace_remains_writable(self) -> None:
        result = self.run_in_sandbox(
            "import os\n"
            "open('written.txt', 'w').write('ok')\n"
            "print('WROTE', os.path.getsize('written.txt'))\n"
        )
        self.assertIn("WROTE", result["stdout"], result)
        self.assertTrue((self.root / "written.txt").is_file())

    def test_timeout_still_applies_inside_the_sandbox(self) -> None:
        result = self.run_in_sandbox("import time; time.sleep(30)", timeout=1)
        self.assertTrue(result["timed_out"])
        self.assertLess(result["seconds"], 20)

    def test_process_children_do_not_survive(self) -> None:
        result = self.run_in_sandbox(
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "print('child', child.pid, flush=True)\n"
            "time.sleep(30)\n",
            timeout=1,
        )
        self.assertTrue(result["timed_out"])


class SandboxPolicyTests(unittest.TestCase):
    def test_require_raises_when_no_backend_exists(self) -> None:
        with patch("babymind.sandbox.backend",
                   return_value=sandbox.Backend("none", False, "no backend in this test")):
            with self.assertRaises(runner.CommandRejected):
                runner.run_command([sys.executable, "-c", "print(1)"], timeout=10, sandbox="require")

    def test_auto_falls_back_and_says_so(self) -> None:
        with patch("babymind.sandbox.backend",
                   return_value=sandbox.Backend("none", False, "no backend in this test")):
            result = runner.run_command([sys.executable, "-c", "print('ran')"],
                                        timeout=20, sandbox="auto")
        self.assertTrue(result["ok"])
        self.assertFalse(result["sandboxed"])
        self.assertEqual(result["sandbox"], "unavailable")

    def test_off_never_touches_the_sandbox(self) -> None:
        result = runner.run_command([sys.executable, "-c", "print(1)"], timeout=20, sandbox="off")
        self.assertFalse(result["sandboxed"])


if __name__ == "__main__":
    unittest.main()
