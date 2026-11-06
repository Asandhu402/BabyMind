"""Repository selection is bounded, deterministic, and does not follow links."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babymind.repository_context import MAX_CONTEXT_CHARS, build_context


class RepositoryContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_relevant_full_file_and_explicit_path_rank_first(self):
        self.put("src/widget.py", "def calculate_widget():\n    return 42\n")
        self.put("src/other.py", "def calculate_widget():\n    pass\n")
        raw = build_context(self.root, "Fix src/widget.py calculate_widget")
        files = json.loads(raw)["files"]
        self.assertEqual(files[0]["path"], "src/widget.py")
        self.assertTrue(files[0]["complete"])
        self.assertEqual(files[0]["content"], "def calculate_widget():\n    return 42\n")
        self.assertLessEqual(len(raw), MAX_CONTEXT_CHARS)

    def test_large_files_are_path_only_and_escaping_obeys_budget(self):
        self.put("large.py", "large = '" + "x" * 7000 + "'\n")
        self.put("escape.py", "escape = '" + "\\\"" * 5000 + "'\n")
        raw = build_context(self.root, "large.py escape.py")
        self.assertLessEqual(len(raw), MAX_CONTEXT_CHARS)
        for entry in json.loads(raw)["files"]:
            self.assertFalse(entry["complete"])
            self.assertNotIn("content", entry)

    def test_incomplete_files_can_include_labeled_relevant_excerpt(self):
        self.put("module.py", "# header\n" * 2000 + "def solve_needle():\n    pass\n")
        entry = json.loads(build_context(self.root, "solve_needle"))["files"][0]
        self.assertFalse(entry["complete"])
        self.assertIn("def solve_needle", entry["excerpt"])
        self.assertGreater(entry["excerpt_start_line"], 1)
        self.assertNotIn("content", entry)

    def test_excludes_protected_hidden_secrets_binary_and_symlinks(self):
        self.put("src/visible.py", "def widget(): pass\n")
        for name in ("state/widget.py", ".hidden/widget.py", "vendor/widget.py",
                     "src/credentials.py", "src/.env.py"):
            self.put(name, "widget = 'sensitive'\n")
        (self.root / "src" / "binary.py").write_bytes(b"widget\0secret")
        (self.root / "link.py").symlink_to(self.root / "src" / "visible.py")
        (self.root / "linked_dir").symlink_to(self.root / "src", target_is_directory=True)
        raw = build_context(self.root, "widget credentials binary link")
        self.assertEqual([f["path"] for f in json.loads(raw)["files"]], ["src/visible.py"])
        self.assertNotIn("sensitive", raw)

    def test_failure_terms_select_relevant_file_and_scan_limit_reported(self):
        self.put("src/bug.py", "def failing_symbol(): pass\n")
        files = json.loads(build_context(self.root, "Repair", failure="failing_symbol"))["files"]
        self.assertEqual(files[0]["path"], "src/bug.py")
        with patch("babymind.repository_context.MAX_FILES_SCANNED", 1):
            self.assertTrue(json.loads(build_context(self.root, "bug"))["scan_limited"])

    def test_no_relevant_files_are_not_invented(self):
        self.put("hello.py", "print('hello')\n")
        self.assertEqual(json.loads(build_context(self.root, "quantumflux"))["files"], [])


if __name__ == "__main__":
    unittest.main()
