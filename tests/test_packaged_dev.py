"""Packaged source staging tests; these do not test runtime activation."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babymind import packaged_dev, selfdev


class PackagedDevTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        seed = self.package / "dev-source-seed"
        (seed / "src" / "babymind").mkdir(parents=True)
        (seed / "src" / "babymind" / "core.py").write_text("VALUE = 1\n")
        (seed / "tests").mkdir()
        helper = self.package / "dev-python" / "bin" / "python3"
        helper.parent.mkdir(parents=True)
        helper.write_text("fixture")
        helper.chmod(0o700)
        self.env = patch.dict(os.environ, {"BABYMIND_HOME": str(self.root / "data")})
        self.env.start()
        self.app = patch.object(packaged_dev, "app_directory", return_value=self.package)
        self.app.start()

    def tearDown(self):
        self.app.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_workspace_created_once_without_overwriting_edits(self):
        root = packaged_dev.workspace()
        path = root / "src" / "babymind" / "core.py"
        self.assertEqual(path.read_text(), "VALUE = 1\n")
        path.write_text("VALUE = 9\n")
        self.assertEqual(packaged_dev.workspace(), root)
        self.assertEqual(path.read_text(), "VALUE = 9\n")
        self.assertEqual((self.package / "dev-source-seed/src/babymind/core.py").read_text(), "VALUE = 1\n")

    def test_changed_package_seed_does_not_overwrite_existing_workspace(self):
        root = packaged_dev.workspace()
        path = root / "src/babymind/core.py"
        path.write_text("user edits\n")
        (self.package / "dev-source-seed/src/babymind/core.py").write_text("new version\n")
        with self.assertRaisesRegex(packaged_dev.PackagedDevelopmentError, "different package version"):
            packaged_dev.workspace()
        self.assertEqual(path.read_text(), "user edits\n")

    def test_existing_unmanaged_workspace_is_never_overwritten(self):
        root = self.root / "data" / "development-source"
        root.mkdir(parents=True)
        (root / "important.txt").write_text("keep")
        with self.assertRaisesRegex(packaged_dev.PackagedDevelopmentError, "not a recognised"):
            packaged_dev.workspace()
        self.assertEqual((root / "important.txt").read_text(), "keep")

    def test_symbolic_links_in_seed_are_rejected(self):
        (self.package / "dev-source-seed/tests/escape.py").symlink_to(self.root / "private")
        with self.assertRaisesRegex(packaged_dev.PackagedDevelopmentError, "symbolic link"):
            packaged_dev.workspace()
        self.assertFalse((self.root / "data" / "development-source").exists())

    def test_frozen_mode_cannot_target_arbitrary_checkout_or_disable_sandbox(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.dict(os.environ, {"BABYMIND_DEV_ROOT": str(self.root), "BABYMIND_SANDBOX": "off"}):
            root = selfdev.dev_root()
            self.assertEqual(root, (self.root / "data/development-source").resolve())
            self.assertEqual(selfdev.sandbox_mode(), "require")
            with self.assertRaisesRegex(selfdev.SelfDevError, "Protected path"):
                selfdev.preview_edits([{"path": ".babymind-development-workspace.json", "content": "{}"}])


if __name__ == "__main__":
    unittest.main()
