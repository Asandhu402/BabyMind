"""Tests for the isolated Linux openat2 workspace primitives."""
import os
import tempfile
import unittest
from pathlib import Path

from babymind.linux_workspace import LinuxWorkspace, WorkspaceSecurityError, sys_is_linux


@unittest.skipUnless(sys_is_linux(), "Linux openat2 backend tests")
class LinuxWorkspaceTests(unittest.TestCase):
    def test_lists_reads_and_creates_relative_to_pinned_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "notes").mkdir()
            (root / "notes" / "a.txt").write_text("hello", encoding="utf-8")
            with LinuxWorkspace(str(root)) as workspace:
                self.assertEqual(workspace.read_file("notes/a.txt"), b"hello")
                self.assertEqual(workspace.list_directory("notes"), [
                    {"name": "a.txt", "type": "file"}
                ])
                self.assertEqual(workspace.create_file("notes/new.txt", b"new"), 3)
                self.assertEqual((root / "notes" / "new.txt").read_bytes(), b"new")

    def test_rejects_symlink_in_intermediate_component(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            (root / "escape").symlink_to(outside, target_is_directory=True)
            (Path(outside) / "secret.txt").write_text("secret", encoding="utf-8")
            with LinuxWorkspace(str(root)) as workspace:
                with self.assertRaises(OSError):
                    workspace.read_file("escape/secret.txt")

    def test_rejects_symlink_as_final_file(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            (Path(outside) / "secret.txt").write_text("secret", encoding="utf-8")
            (root / "secret.txt").symlink_to(Path(outside) / "secret.txt")
            with LinuxWorkspace(str(root)) as workspace:
                with self.assertRaises(OSError):
                    workspace.read_file("secret.txt")

    def test_root_admission_rejects_symlink_ancestor(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            real = base / "real"
            real.mkdir()
            alias = base / "alias"
            alias.symlink_to(real, target_is_directory=True)
            with self.assertRaises(OSError):
                LinuxWorkspace(str(alias))

    def test_rejects_traversal_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp, LinuxWorkspace(temp) as workspace:
            for path in ("../outside", "/etc/passwd", "a//b", "./a"):
                with self.subTest(path=path), self.assertRaises(WorkspaceSecurityError):
                    workspace.read_file(path)

    def test_creation_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "already.txt").write_text("original", encoding="utf-8")
            with LinuxWorkspace(str(root)) as workspace:
                with self.assertRaises(FileExistsError):
                    workspace.create_file("already.txt", b"changed")
            self.assertEqual((root / "already.txt").read_text(encoding="utf-8"), "original")

    def test_read_size_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "large.txt").write_bytes(b"x" * 10)
            with LinuxWorkspace(str(root)) as workspace:
                with self.assertRaises(WorkspaceSecurityError):
                    workspace.read_file("large.txt", max_bytes=5)


if __name__ == "__main__":
    unittest.main()
