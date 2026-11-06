"""Tests for the self-development engine (checkpoints, apply, verify, rollback)."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from babymind import sandbox, selfdev


def _make_checkout(root: Path) -> None:
    (root / "src" / "babymind").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
    (root / "src" / "babymind" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "babymind" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_ok.py").write_text(
        "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
        "    def test_ok(self):\n        self.assertEqual(1, 1)\n",
        encoding="utf-8",
    )


class SelfDevTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        _make_checkout(self.root)
        self.env = patch.dict(os.environ, {
            "BABYMIND_DEV_ROOT": str(self.root),
            "BABYMIND_SELF_DEVELOPMENT_ENABLED": "true",
            # Unit fixtures contain only trusted test code; boundary tests are separate.
            "BABYMIND_SANDBOX": "off",
        })
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def test_default_and_invalid_sandbox_modes_fail_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(selfdev.sandbox_mode(), "require")
        with patch.dict(os.environ, {"BABYMIND_SANDBOX": "typo"}):
            self.assertEqual(selfdev.sandbox_mode(), "require")

    def test_self_edit_without_required_sandbox_does_not_write(self) -> None:
        with patch.dict(os.environ, {"BABYMIND_SANDBOX": "require"}), \
             patch.object(sandbox, "backend", return_value=sandbox.Backend("none", False, "blocked")):
            with self.assertRaisesRegex(selfdev.SelfDevError, "not verified"):
                selfdev.apply_edits([{"path": "src/babymind/mod.py", "content": "VALUE = 2\n"}])
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")

    def test_failed_boundary_probe_does_not_write(self) -> None:
        with patch.dict(os.environ, {"BABYMIND_SANDBOX": "require"}), \
             patch.object(sandbox, "self_test", return_value={"verified": False}):
            with self.assertRaisesRegex(selfdev.SelfDevError, "not verified"):
                selfdev.apply_edits([{"path": "src/babymind/mod.py", "content": "VALUE = 2\n"}])
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")

    def test_status_reports_real_capabilities(self) -> None:
        report = selfdev.status()
        self.assertTrue(report["enabled"])
        self.assertTrue(report["can_write_source"])
        self.assertFalse(report["requires_per_change_approval"])
        self.assertFalse(report["isolation"]["os_sandbox"])
        self.assertEqual(Path(report["root"]), self.root.resolve())

    def test_checkpoint_captures_the_project(self) -> None:
        record = selfdev.checkpoint("before change", reason="test")
        self.assertIn("src/babymind/mod.py", record["files"])
        self.assertIn("tests/test_ok.py", record["files"])
        self.assertEqual(selfdev.list_checkpoints()[0]["id"], record["id"])

    def test_apply_is_verified_and_recorded(self) -> None:
        result = selfdev.apply_edits(
            [{"path": "src/babymind/mod.py", "content": "VALUE = 2\n"}],
            reason="bump value",
        )
        self.assertEqual(result["status"], "applied", result)
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 2\n")
        self.assertTrue(result["compile"]["ok"])
        self.assertTrue(result["tests"]["summary"]["passed"])
        self.assertTrue(selfdev.verify_audit_chain()["valid"])

    def test_partial_write_failure_restores_existing_and_removes_created_files(self) -> None:
        original_link = os.link
        def fail_last_edit(source, destination):
            if Path(destination).name == "last.py" and ".bmedit-" in str(source):
                raise OSError("simulated write failure")
            return original_link(source, destination)

        with patch("babymind.selfdev.os.link", side_effect=fail_last_edit):
            with self.assertRaisesRegex(selfdev.SelfDevError, "reverted"):
                selfdev.apply_edits([
                    {"path": "src/babymind/mod.py", "content": "VALUE = 99\n"},
                    {"path": "src/babymind/new.py", "content": "VALUE = 2\n"},
                    {"path": "src/babymind/last.py", "content": "VALUE = 3\n"},
                ], verify=False)
        self.assertEqual((self.root / "src/babymind/mod.py").read_text(), "VALUE = 1\n")
        self.assertFalse((self.root / "src/babymind/new.py").exists())
        self.assertFalse((self.root / "src/babymind/last.py").exists())
        self.assertEqual(list((self.root / "src/babymind").glob("*.bmedit-*")), [])

    def test_missing_checkpoint_backup_blocks_edit(self) -> None:
        with patch("babymind.selfdev.MAX_SNAPSHOT_BYTES", 1):
            with self.assertRaisesRegex(selfdev.SelfDevError, "missing from the checkpoint"):
                selfdev.apply_edits([{"path": "src/babymind/mod.py", "content": "VALUE = 99\n"}], verify=False)
        self.assertEqual((self.root / "src/babymind/mod.py").read_text(), "VALUE = 1\n")

    def test_new_file_that_appears_during_transaction_is_preserved(self) -> None:
        target = self.root / "src/babymind/new.py"
        original_link = os.link
        def another_writer(source, destination):
            target.write_text("USER_DATA = True\n")
            return original_link(source, destination)
        with patch("babymind.selfdev.os.link", side_effect=another_writer):
            with self.assertRaisesRegex(selfdev.SelfDevError, "reverted"):
                selfdev.apply_edits([{"path": "src/babymind/new.py", "content": "VALUE = 2\n"}], verify=False)
        self.assertEqual(target.read_text(), "USER_DATA = True\n")

    def test_rollback_failure_is_not_reported_as_success(self) -> None:
        original_link = os.link
        def fail_last(source, destination):
            if Path(destination).name == "last.py":
                raise OSError("write failed")
            return original_link(source, destination)
        with patch("babymind.selfdev.os.link", side_effect=fail_last), \
             patch("babymind.selfdev.rollback", side_effect=OSError("restore failed")):
            with self.assertRaisesRegex(selfdev.SelfDevError, "automatic rollback failed.*checkpoint"):
                selfdev.apply_edits([
                    {"path": "src/babymind/mod.py", "content": "VALUE = 99\n"},
                    {"path": "src/babymind/last.py", "content": "VALUE = 3\n"},
                ], verify=False)

    def test_verification_exception_rolls_back_only_edited_files(self) -> None:
        unrelated = self.root / "src/babymind/unrelated.py"
        unrelated.write_text("before = 1\n")
        def failed_compile(*args, **kwargs):
            unrelated.write_text("user_change = 2\n")
            raise RuntimeError("verification infrastructure failed")
        with patch("babymind.selfdev.runner.run_compile_check", side_effect=failed_compile):
            with self.assertRaisesRegex(selfdev.SelfDevError, "change was reverted"):
                selfdev.apply_edits([
                    {"path": "src/babymind/mod.py", "content": "VALUE = 99\n"},
                    {"path": "src/babymind/new.py", "content": "VALUE = 2\n"},
                ], verify=False)
        self.assertEqual((self.root / "src/babymind/mod.py").read_text(), "VALUE = 1\n")
        self.assertFalse((self.root / "src/babymind/new.py").exists())
        self.assertEqual(unrelated.read_text(), "user_change = 2\n")

    def test_rollback_does_not_overwrite_later_change_to_edited_file(self) -> None:
        edited = self.root / "src/babymind/mod.py"
        def compile_fails(*args, **kwargs):
            edited.write_text("USER_CHANGE = 42\n")
            return {"ok": False}
        with patch("babymind.selfdev.runner.run_compile_check", side_effect=compile_fails):
            with self.assertRaisesRegex(selfdev.SelfDevError, "automatic rollback failed.*manual recovery"):
                selfdev.apply_edits([{"path": "src/babymind/mod.py", "content": "VALUE = 99\n"}], verify=False)
        self.assertEqual(edited.read_text(), "USER_CHANGE = 42\n")

    def test_failed_verification_preserves_unrelated_concurrent_edit(self) -> None:
        unrelated = self.root / "src/babymind/unrelated.py"
        unrelated.write_text("before = 1\n")
        def compile_fails(*args, **kwargs):
            unrelated.write_text("user_change = 2\n")
            return {"ok": False}
        with patch("babymind.selfdev.runner.run_compile_check", side_effect=compile_fails):
            result = selfdev.apply_edits([
                {"path": "src/babymind/mod.py", "content": "VALUE = 99\n"},
            ], verify=False)
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual((self.root / "src/babymind/mod.py").read_text(), "VALUE = 1\n")
        self.assertEqual(unrelated.read_text(), "user_change = 2\n")

    def test_new_file_is_created_and_removable_by_rollback(self) -> None:
        result = selfdev.apply_edits(
            [{"path": "src/babymind/extra.py", "content": "FLAG = True\n"}],
            reason="add module",
        )
        self.assertEqual(result["status"], "applied", result)
        created = self.root / "src" / "babymind" / "extra.py"
        self.assertTrue(created.is_file())
        selfdev.rollback(result["checkpoint_id"])
        self.assertFalse(created.is_file())

    def test_failing_change_is_rolled_back_automatically(self) -> None:
        original = (self.root / "tests" / "test_ok.py").read_text(encoding="utf-8")
        broken = original.replace("assertEqual(1, 1)", "assertEqual(1, 2)")
        result = selfdev.apply_edits(
            [{"path": "tests/test_ok.py", "content": broken}],
            reason="deliberately break a test",
        )
        self.assertEqual(result["status"], "rolled_back", result)
        self.assertEqual((self.root / "tests" / "test_ok.py").read_text(encoding="utf-8"), original)
        self.assertIn("regressed", result["reason"])
        actions = [entry["action"] for entry in selfdev.audit_entries(20)]
        self.assertIn("auto_rollback", actions)

    def test_compile_failure_is_rolled_back(self) -> None:
        original = (self.root / "src" / "babymind" / "mod.py").read_text(encoding="utf-8")
        result = selfdev.apply_edits(
            [{"path": "src/babymind/mod.py", "content": "def broken(:\n"}],
            reason="syntax error",
        )
        self.assertEqual(result["status"], "rolled_back", result)
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(encoding="utf-8"), original)

    def test_rollback_restores_previous_content(self) -> None:
        record = selfdev.checkpoint("manual")
        (self.root / "src" / "babymind" / "mod.py").write_text("VALUE = 99\n", encoding="utf-8")
        selfdev.rollback(record["id"])
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")

    def test_protected_paths_are_rejected(self) -> None:
        for path in ("../outside.py", "/etc/passwd", ".git/config", "state/dev-audit.jsonl",
                     "memory.key", "data.sqlite3", "model.gguf"):
            with self.subTest(path=path), self.assertRaises(selfdev.SelfDevError):
                selfdev.preview_edits([{"path": path, "content": "x = 1\n"}])

    def test_permission_is_checked_against_the_role_registry(self) -> None:
        with self.assertRaises(PermissionError):
            selfdev.apply_edits(
                [{"path": "src/babymind/mod.py", "content": "VALUE = 3\n"}],
                agent_id="BM-27",  # UI/UX Designer has no repo.write capability
            )

    def test_disabled_gate_blocks_writes(self) -> None:
        with patch.dict(os.environ, {"BABYMIND_SELF_DEVELOPMENT_ENABLED": "false"}):
            self.assertFalse(selfdev.selfdev_enabled())
            with self.assertRaises(selfdev.SelfDevError):
                selfdev.apply_edits([{"path": "src/babymind/mod.py", "content": "VALUE = 4\n"}])

    def test_purge_bytecode_stays_within_source_and_tests(self) -> None:
        for relative in ("src/babymind/__pycache__/a.pyc", "tests/__pycache__/b.pyc",
                         ".venv/lib/__pycache__/keep.pyc", "vendor/__pycache__/keep.pyc",
                         "state/__pycache__/keep.pyc", "__pycache__/keep.pyc"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        selfdev.purge_bytecode(self.root)
        self.assertFalse((self.root / "src/babymind/__pycache__").exists())
        self.assertFalse((self.root / "tests/__pycache__").exists())
        for relative in (".venv/lib/__pycache__/keep.pyc", "vendor/__pycache__/keep.pyc",
                         "state/__pycache__/keep.pyc", "__pycache__/keep.pyc"):
            self.assertTrue((self.root / relative).exists(), relative)

    def test_symlink_components_are_rejected_even_within_workspace(self) -> None:
        protected = self.root / "state" / "private.py"
        protected.parent.mkdir()
        protected.write_text("secret = True\n")
        direct = self.root / "src" / "babymind" / "alias.py"
        direct.symlink_to(protected)
        linked_dir = self.root / "src" / "linked"
        linked_dir.symlink_to(protected.parent, target_is_directory=True)
        broken = self.root / "src" / "babymind" / "missing.py"
        broken.symlink_to(self.root / "missing-target.py")
        for path in ("src/babymind/alias.py", "src/linked/private.py", "src/babymind/missing.py"):
            with self.subTest(path=path), self.assertRaisesRegex(selfdev.SelfDevError, "Symbolic links"):
                selfdev.preview_edits([{"path": path, "content": "changed = True\n"}])
            with self.subTest(path=path), self.assertRaisesRegex(selfdev.SelfDevError, "Symbolic links"):
                selfdev.read_file(path)
        self.assertEqual(protected.read_text(), "secret = True\n")

    def test_preview_reports_a_diff_without_writing(self) -> None:
        reviewed = selfdev.preview_edits([{"path": "src/babymind/mod.py", "content": "VALUE = 5\n"}])
        self.assertIn("-VALUE = 1", reviewed[0]["diff"])
        self.assertIn("+VALUE = 5", reviewed[0]["diff"])
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")

    def test_tree_and_read_file(self) -> None:
        paths = {item["path"] for item in selfdev.tree()}
        self.assertIn("pyproject.toml", paths)
        content = selfdev.read_file("src/babymind/mod.py")
        self.assertIn("VALUE = 1", content["content"])

    def test_audit_chain_detects_tampering(self) -> None:
        selfdev.checkpoint("one")
        selfdev.checkpoint("two")
        path = self.root / "state" / "dev-audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[0] = lines[0].replace('"label": "one"', '"label": "edited"')
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertFalse(selfdev.verify_audit_chain()["valid"])

    def test_edit_that_removes_all_tests_is_rolled_back(self) -> None:
        test_path = self.root / "tests" / "test_ok.py"
        original = test_path.read_text()
        result = selfdev.apply_edits([{"path": "tests/test_ok.py", "content": "# no tests\n"}])
        self.assertEqual(result["status"], "rolled_back", result)
        self.assertIn("runnable tests", result["reason"])
        self.assertEqual(test_path.read_text(), original)

    def test_edit_that_skips_an_existing_test_is_rolled_back(self) -> None:
        (self.root / "tests" / "test_extra.py").write_text(
            "import unittest\nclass Extra(unittest.TestCase):\n def test_more(self): pass\n")
        test_path = self.root / "tests" / "test_ok.py"
        original = test_path.read_text()
        result = selfdev.apply_edits([{"path": "tests/test_ok.py", "content":
            "import unittest\nclass Ok(unittest.TestCase):\n"
            " @unittest.skip('disabled')\n def test_ok(self): pass\n"}])
        self.assertEqual(result["status"], "rolled_back", result)
        self.assertIn("skipped", result["reason"])
        self.assertEqual(test_path.read_text(), original)

    def test_crashed_post_edit_test_runner_is_rolled_back(self) -> None:
        real_run = selfdev.runner.run_unit_tests
        def run_then_crash(root, **kwargs):
            result = real_run(root, **kwargs)
            if (self.root / "src" / "babymind" / "mod.py").read_text() == "VALUE = 2\n":
                result.update(ok=False, exit_code=-9, timed_out=False)
            return result
        with patch.object(selfdev.runner, "run_unit_tests", side_effect=run_then_crash):
            result = selfdev.apply_edits([{"path": "src/babymind/mod.py", "content": "VALUE = 2\n"}])
        self.assertEqual(result["status"], "rolled_back", result)
        self.assertIn("did not complete", result["reason"])
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")

    def test_empty_pre_edit_suite_blocks_write(self) -> None:
        (self.root / "tests" / "test_ok.py").write_text("# no tests\n")
        with self.assertRaisesRegex(selfdev.SelfDevError, "pre-edit test suite") as caught:
            selfdev.apply_edits([{"path": "src/babymind/mod.py", "content": "VALUE = 2\n"}])
        # The refusal must name its own cause: a hosted run cannot be re-run to
        # find out which of the three gate conditions fired.
        message = str(caught.exception)
        for field in ("ran=", "skipped=", "problems=", "identified=", "timed_out=", "truncated="):
            self.assertIn(field, message)
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")

    def test_suite_diagnosis_reports_the_counters_the_gate_uses(self) -> None:
        diagnosis = selfdev._suite_diagnosis({
            "summary": {"ran": 12, "skipped": 3, "problems": 2},
            "exit_code": 1,
            "timed_out": False,
            "truncated": True,
            "stderr": "FAIL: one.test\nERROR: two.test\n" + "noise" * 40,
        })
        self.assertIn("ran=12", diagnosis)
        self.assertIn("skipped=3", diagnosis)
        self.assertIn("problems=2", diagnosis)
        self.assertIn("identified=2", diagnosis)
        self.assertIn("exit=1", diagnosis)
        self.assertIn("timed_out=False", diagnosis)
        self.assertIn("truncated=True", diagnosis)
        # 15 + 16 + 200 bytes of stderr; the point is that the real length is
        # reported, not a recomputed stand-in for it.
        self.assertIn("output_chars=231", diagnosis)

    def test_suite_diagnosis_survives_a_result_without_counters(self) -> None:
        diagnosis = selfdev._suite_diagnosis({})
        self.assertIn("ran=0", diagnosis)
        self.assertIn("identified=0", diagnosis)
        self.assertIn("output_chars=0", diagnosis)

    def test_preexisting_failure_does_not_block_a_good_change(self) -> None:
        (self.root / "tests" / "test_known_failure.py").write_text(
            "import unittest\n\n\nclass Known(unittest.TestCase):\n"
            "    def test_known(self):\n        self.fail('pre-existing failure')\n",
            encoding="utf-8",
        )
        result = selfdev.apply_edits(
            [{"path": "src/babymind/mod.py", "content": "VALUE = 10\n"}],
            reason="good change with a broken baseline",
        )
        self.assertEqual(result["status"], "applied", result)
        self.assertEqual(result["baseline"]["problems"], 1)

    def test_new_failure_cannot_replace_a_known_baseline_failure(self) -> None:
        known = self.root / "tests" / "test_known_failure.py"
        known.write_text("import unittest\nclass Known(unittest.TestCase):\n"
                         " def test_known(self): self.fail('known failure')\n")
        original_known = known.read_text()
        ok = self.root / "tests" / "test_ok.py"
        original_ok = ok.read_text()
        result = selfdev.apply_edits([
            {"path": "tests/test_known_failure.py", "content":
             "import unittest\nclass Known(unittest.TestCase):\n def test_known(self): pass\n"},
            {"path": "tests/test_ok.py", "content":
             "import unittest\nclass Ok(unittest.TestCase):\n def test_ok(self): self.fail('new failure')\n"},
        ])
        self.assertEqual(result["status"], "rolled_back", result)
        self.assertIn("previously passing test", result["reason"])
        self.assertEqual(known.read_text(), original_known)
        self.assertEqual(ok.read_text(), original_ok)

    def test_new_failure_above_baseline_is_rolled_back(self) -> None:
        (self.root / "tests" / "test_known_failure.py").write_text(
            "import unittest\n\n\nclass Known(unittest.TestCase):\n"
            "    def test_known(self):\n        self.fail('pre-existing failure')\n",
            encoding="utf-8",
        )
        first = selfdev.apply_edits(
            [{"path": "src/babymind/mod.py", "content": "VALUE = 11\n"}],
            reason="establish baseline",
        )
        self.assertEqual(first["status"], "applied", first)
        second = selfdev.apply_edits(
            [{"path": "tests/test_ok.py", "content": "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
                                                      "    def test_ok(self):\n        self.assertEqual(1, 2)\n"}],
            reason="introduce a second failure",
        )
        self.assertEqual(second["status"], "rolled_back", second)
        self.assertIn("regressed", second["reason"])

    def test_repair_loop_retries_only_after_a_rollback(self) -> None:
        seen: list[tuple[int, str]] = []

        def propose(attempt: int, failure: str):
            seen.append((attempt, failure))
            if attempt == 1:
                return [{"path": "tests/test_ok.py",
                         "content": "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
                                    "    def test_ok(self):\n        self.assertEqual(1, 9)\n"}]
            return [{"path": "tests/test_ok.py",
                     "content": "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
                                "    def test_ok(self):\n        self.assertEqual(4, 4)\n"}]

        outcome = selfdev.apply_with_repair(propose, attempts=2, reason="repair demo")
        self.assertEqual(outcome["status"], "applied", outcome)
        self.assertEqual(outcome["attempts"], 2)
        self.assertEqual([item["status"] for item in outcome["history"]], ["rolled_back", "applied"])
        self.assertEqual(seen[0][1], "")
        self.assertIn("assertEqual", seen[1][1])
        self.assertIn("assertEqual(4, 4)", (self.root / "tests" / "test_ok.py").read_text())

    def test_repair_loop_retries_after_an_unparseable_proposal(self) -> None:
        # A proposer that raised used to end the loop at once, so the attempts
        # the caller paid for were never used and the error was never reported
        # back to the model.
        seen: list[tuple[int, str]] = []

        def propose(attempt: int, failure: str):
            seen.append((attempt, failure))
            if attempt == 1:
                raise ValueError("the model returned an unterminated JSON object")
            return [{"path": "src/babymind/mod.py", "content": "VALUE = 2\n"}]

        outcome = selfdev.apply_with_repair(propose, attempts=2, reason="parse retry")
        self.assertEqual(outcome["status"], "applied", outcome)
        self.assertEqual([item["status"] for item in outcome["history"]],
                         ["proposer_error", "applied"])
        self.assertEqual(seen[0][1], "")
        self.assertTrue(seen[1][1].startswith(selfdev.PROPOSER_ERROR_PREFIX), seen[1][1])
        self.assertIn("unterminated JSON object", seen[1][1])

    def test_repair_loop_still_gives_up_when_every_proposal_is_unparseable(self) -> None:
        calls = []

        def propose(attempt: int, failure: str):
            calls.append(attempt)
            raise ValueError("the model returned an unterminated JSON object")

        outcome = selfdev.apply_with_repair(propose, attempts=3, reason="always bad")
        self.assertEqual(outcome["status"], "unrepaired")
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual([item["status"] for item in outcome["history"]], ["proposer_error"] * 3)
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")

    def test_repair_loop_gives_up_and_restores_the_tree(self) -> None:
        calls = []

        def propose(attempt: int, failure: str):
            calls.append(attempt)
            return [{"path": "src/babymind/mod.py", "content": "def broken(:\n"}]

        outcome = selfdev.apply_with_repair(propose, attempts=3, reason="never works")
        self.assertEqual(outcome["status"], "unrepaired")
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")
        self.assertTrue(outcome["last_failure"])

    def test_repair_loop_stops_when_nothing_is_proposed(self) -> None:
        calls = []

        def propose(attempt: int, failure: str):
            calls.append(attempt)
            return []

        outcome = selfdev.apply_with_repair(propose, attempts=3, reason="nothing")
        self.assertEqual(outcome["status"], "unrepaired")
        self.assertEqual(calls, [1])
        self.assertEqual(outcome["history"][-1]["status"], "no_change")

    def test_repair_loop_records_its_outcome_in_the_audit_chain(self) -> None:
        def propose(attempt: int, failure: str):
            return [{"path": "src/babymind/mod.py", "content": f"VALUE = {attempt + 1}\n"}]

        outcome = selfdev.apply_with_repair(propose, attempts=1, reason="audited repair")
        self.assertEqual(outcome["status"], "applied")
        audit = selfdev.verify_audit_chain()
        self.assertTrue(audit["valid"], audit)
        actions = [entry.get("action") for entry in selfdev.audit_entries(50)]
        self.assertIn("repair_succeeded", actions)


if __name__ == "__main__":
    unittest.main()


class UpgradeTests(unittest.TestCase):
    def test_upgrade_requires_confirmation(self):
        from babymind import upgrade
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.upgrade("not the confirmation")

    def test_upgrade_source_checkout_reports_already_live(self):
        from babymind import upgrade
        result = upgrade.upgrade(upgrade.UPGRADE_CONFIRMATION)
        self.assertFalse(result["upgraded"])
        self.assertIn("source checkout", result["notice"])

    def test_preview_state_when_not_running(self):
        from babymind import upgrade
        self.assertEqual(upgrade.preview_state(), {"running": False})
