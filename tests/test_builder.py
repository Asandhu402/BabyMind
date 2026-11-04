"""Tests for the opt-in local app builder."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from babymind import builder


class StaticProvider:
    """Minimal ChatProvider stand-in that returns a fixed plan."""

    def __init__(self, payload: dict | str) -> None:
        self.payload = payload

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload)


def _sample_payload(entry: str = "app.py") -> dict:
    return {
        "name": "Hello App",
        "summary": "Prints a greeting.",
        "entry": entry,
        "files": [
            {"path": "app.py", "content": 'print("hello from generated app")\n'},
            {"path": "README.md", "content": "# Hello App\n"},
        ],
    }


class BuilderPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "apps").mkdir()
        self.env = patch.dict(os.environ, {
            "BABYMIND_APP_BUILDER_ENABLED": "true",
            "BABYMIND_BUILDER_ROOT": str(self.root),
        })
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def test_plan_requires_approval_and_validates_files(self) -> None:
        plan = builder.build_plan(
            "Hello App", "app.py", _sample_payload()["files"], summary="greeting"
        )
        self.assertEqual(plan["target"], "apps/hello-app")
        self.assertEqual(plan["entry"], "app.py")
        self.assertEqual(len(plan["plan_hash"]), 64)
        builder.verify_plan(plan, plan["plan_hash"])  # exact hash is accepted

    def test_tampered_plan_is_rejected(self) -> None:
        plan = builder.build_plan("Hello App", "app.py", _sample_payload()["files"])
        plan["files"][0]["content"] = 'print("something else")\n'
        with self.assertRaises(builder.BuilderError):
            builder.apply_plan(plan, plan["plan_hash"])

    def test_approval_must_match_the_reviewed_hash(self) -> None:
        plan = builder.build_plan("Hello App", "app.py", _sample_payload()["files"])
        with self.assertRaises(builder.BuilderError):
            builder.apply_plan(plan, "0" * 64)

    def test_parent_traversal_is_rejected(self) -> None:
        with self.assertRaises(builder.BuilderError):
            builder.build_plan("Escape", None, [{"path": "../outside.py", "content": "x = 1\n"}])

    def test_absolute_and_hidden_paths_are_rejected(self) -> None:
        for path in ("/etc/passwd.py", "C:/Windows/evil.py", ".env.py", "sub/../../x.py"):
            with self.subTest(path=path), self.assertRaises(builder.BuilderError):
                builder.build_plan("Bad", None, [{"path": path, "content": "x = 1\n"}])

    def test_disallowed_suffix_is_rejected(self) -> None:
        with self.assertRaises(builder.BuilderError):
            builder.build_plan("Bad", None, [{"path": "run.exe", "content": "MZ"}])

    def test_entry_must_be_a_generated_python_file(self) -> None:
        with self.assertRaises(builder.BuilderError):
            builder.build_plan("Bad", "missing.py", _sample_payload()["files"])
        with self.assertRaises(builder.BuilderError):
            builder.build_plan("Bad", "README.md", _sample_payload()["files"])

    def test_existing_app_folder_is_never_reused(self) -> None:
        (self.root / "apps" / "hello-app").mkdir()
        with self.assertRaises(builder.BuilderError):
            builder.build_plan("Hello App", "app.py", _sample_payload()["files"])

    def test_plan_response_tolerates_code_fences(self) -> None:
        fenced = "```json\n" + json.dumps(_sample_payload()) + "\n```"
        parsed = builder.parse_plan_response(fenced)
        self.assertEqual(parsed["name"], "Hello App")

    def test_plan_response_without_json_is_reported(self) -> None:
        with self.assertRaises(builder.BuilderError):
            builder.parse_plan_response("Sure! Here is your app.")

    def test_create_plan_uses_the_local_provider(self) -> None:
        plan = builder.create_plan("a greeting app", StaticProvider(_sample_payload()))
        self.assertEqual(plan["name"], "Hello App")
        self.assertTrue(plan["will_run"])

    def test_disabled_without_the_environment_gate(self) -> None:
        with patch.dict(os.environ, {"BABYMIND_APP_BUILDER_ENABLED": ""}):
            self.assertFalse(builder.builder_enabled())
            self.assertFalse(builder.builder_status()["ready"])
            with self.assertRaises(builder.BuilderError):
                builder.create_plan("anything", StaticProvider(_sample_payload()))

    def test_status_reports_honest_capabilities(self) -> None:
        status = builder.builder_status()
        self.assertTrue(status["ready"])
        self.assertTrue(status["can_write_files"])
        self.assertFalse(status["can_run_shell_commands"])
        self.assertFalse(status["sandboxed"])
        self.assertEqual(status["limits"]["run_timeout_seconds"], builder.BUILD_TIMEOUT_SECONDS)


class BuilderExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "apps").mkdir()
        self.env = patch.dict(os.environ, {
            "BABYMIND_APP_BUILDER_ENABLED": "true",
            "BABYMIND_BUILDER_ROOT": str(self.root),
        })
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def test_approved_plan_writes_files_and_runs_the_entry_point(self) -> None:
        plan = builder.build_plan("Hello App", "app.py", _sample_payload()["files"])
        result = builder.apply_plan(plan, plan["plan_hash"])
        app_dir = self.root / "apps" / "hello-app"
        self.assertTrue((app_dir / "app.py").is_file())
        self.assertTrue((app_dir / "README.md").is_file())
        self.assertEqual(result["run"]["exit_code"], 0)
        self.assertIn("hello from generated app", result["run"]["stdout"])
        self.assertEqual(result["files"][0]["bytes"], len(b'print("hello from generated app")\n'))

    def test_static_plan_writes_without_running_anything(self) -> None:
        files = [{"path": "index.html", "content": "<!doctype html><title>Hi</title>"}]
        plan = builder.build_plan("Static Site", None, files)
        result = builder.apply_plan(plan, plan["plan_hash"])
        self.assertFalse(result["run"]["ran"])
        self.assertTrue((self.root / "apps" / "static-site" / "index.html").is_file())

    def test_failing_entry_point_is_reported_not_raised(self) -> None:
        files = [{"path": "app.py", "content": "raise SystemExit(3)\n"}]
        plan = builder.build_plan("Broken App", "app.py", files)
        result = builder.apply_plan(plan, plan["plan_hash"])
        self.assertEqual(result["run"]["exit_code"], 3)
        self.assertFalse(result["run"]["timed_out"])

    def test_plan_hash_covers_file_contents(self) -> None:
        first = builder.build_plan("Hello App", "app.py", _sample_payload()["files"])
        changed = _sample_payload()["files"]
        changed[0]["content"] = 'print("different")\n'
        second = builder.build_plan("Hello App", "app.py", changed)
        self.assertNotEqual(first["plan_hash"], second["plan_hash"])


if __name__ == "__main__":
    unittest.main()
