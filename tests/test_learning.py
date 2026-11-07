"""Tests for the verified learning cycle.

These tests verify that the learning cycle can identify a weakness, propose
and verify a fix through the real self-development machinery, evaluate
behaviorally, keep or roll back based on the combination of verification
and behavioral evaluation, and record lessons. The model responses are
scripted, so the tests exercise the machinery -- they do not measure whether
the model would find a good weakness or evaluate a fix well.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import babymind.coding_engine
import babymind.learning
from babymind.independence import Independence
from babymind.learning import LearningCycle, LearningStore
from babymind.secure_store import SecureTextStore
from babymind.selfmodel import SelfModel


class ScriptedProvider:
    """A provider that returns scripted responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self._calls.append((system, user))
        if not self._responses:
            return json_response({"reasoning": "(no scripted response)"})
        text = self._responses.pop(0)
        if callable(text):
            return text(system, user)
        return text

    @property
    def calls(self):
        return self._calls


def json_response(payload: dict) -> str:
    import json as _json
    return _json.dumps(payload)


def _make_store(tmp: Path) -> LearningStore:
    """Create a LearningStore with its own key and database."""
    secure = SecureTextStore(tmp / "learning.key")
    store = LearningStore(secure, tmp / "learning.sqlite3")
    store._initialise()
    return store


class ScriptedDevelop:
    """A callable that replaces coding_engine.develop, returning scripted results."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, provider, task, *, attempts=2, **kwargs):
        self.calls.append({"task": task, "attempts": attempts, **kwargs})
        if not self._responses:
            return {
                "status": "unrepaired", "attempts": 0, "history": [],
                "result": {}, "notice": "",
            }
        return self._responses.pop(0)


class LearningStoreTests(unittest.TestCase):
    def test_init_and_persist(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = _make_store(tmp)
            store.record_weakness("A hash algorithm weakness.", location="selfmodel.py")
            store2 = _make_store(tmp)
            self.assertEqual(len(store2.weaknesses()), 1)
            self.assertEqual(store2.weaknesses()[0]["location"], "selfmodel.py")

    def test_record_and_load_weakness(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = _make_store(tmp)
            w = store.record_weakness(
                "A weakness.", location="file.py", why_it_matters="It matters.",
                proposed_fix="Add a check.", fix_confidence=0.7,
            )
            self.assertEqual(w["weakness"], "A weakness.")
            self.assertEqual(w["status"], "identified")
            self.assertAlmostEqual(w["fix_confidence"], 0.7, delta=1e-6)
            loaded = store.weakness(w["id"])
            self.assertEqual(loaded["location"], "file.py")
            self.assertEqual(loaded["proposed_fix"], "Add a check.")

    def test_weakness_rejects_empty(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = _make_store(tmp)
            with self.assertRaises(ValueError):
                store.record_weakness("")

    def test_weakness_rejects_bad_status(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = _make_store(tmp)
            w = store.record_weakness("A weakness.")
            with self.assertRaises(ValueError):
                store.set_weakness_status(w["id"], "bogus")

    def test_set_weakness_status(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = _make_store(tmp)
            w = store.record_weakness("A weakness.")
            self.assertTrue(store.set_weakness_status(w["id"], "addressed"))
            self.assertEqual(store.weakness(w["id"])["status"], "addressed")
            self.assertFalse(store.set_weakness_status("nope", "addressed"))

    def test_record_and_load_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = _make_store(tmp)
            w = store.record_weakness("A weakness.")
            cycle = store.record_cycle(
                weakness_id=w["id"], weakness="A weakness.", fix_status="applied",
                fix_files=["a.py"], fix_note="Fixed it.", effective=True,
                evaluation_reasoning="The fix addresses the issue.", decision="kept",
                lesson="A good fix.", prediction_id="p-1", prediction_outcome="correct",
            )
            self.assertEqual(cycle["decision"], "kept")
            self.assertEqual(cycle["fix_files"], ["a.py"])
            self.assertTrue(cycle["effective"])
            loaded = store.cycle(cycle["id"])
            self.assertEqual(loaded["lesson"], "A good fix.")
            self.assertEqual(loaded["prediction_id"], "p-1")

    def test_cycles_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = _make_store(tmp)
            w = store.record_weakness("A weakness.")
            store.record_cycle(
                weakness_id=w["id"], weakness="A weakness.", fix_status="applied",
                fix_files=[], fix_note="", effective=True, evaluation_reasoning="",
                decision="kept", lesson="",
            )
            store.record_cycle(
                weakness_id=w["id"], weakness="A weakness.", fix_status="applied",
                fix_files=[], fix_note="", effective=False, evaluation_reasoning="",
                decision="rolled_back", lesson="",
            )
            report = store.report()
            self.assertEqual(report["cycles_total"], 2)
            self.assertEqual(report["cycles_by_decision"]["kept"], 1)
            self.assertEqual(report["cycles_by_decision"]["rolled_back"], 1)
            self.assertEqual(report["weaknesses_by_status"]["identified"], 1)
            self.assertTrue(report["audit_chain_intact"])

    def test_audit_chain_verifies(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = _make_store(tmp)
            store.record_weakness("A weakness.")
            self.assertEqual(store.verify_audit_chain()["entries"], 1)
            self.assertTrue(store.verify_audit_chain()["intact"])

    def test_tamper_detected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = _make_store(tmp)
            store.record_weakness("A weakness.")
            with store.lock:
                db = store._connect()
                # Tamper with the audit chain's entry hash
                db.execute(
                    "UPDATE learning_audit SET entry_hash=? WHERE seq=?",
                    ("0" * 63 + "1", 1),
                )
                db.commit()
                db.close()
            self.assertFalse(store.verify_audit_chain()["intact"])

    def test_report_excludes_unknown_decision(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = _make_store(tmp)
            w = store.record_weakness("A weakness.")
            store.record_cycle(
                weakness_id=w["id"], weakness="A weakness.", fix_status="applied",
                fix_files=[], fix_note="", effective=False, evaluation_reasoning="",
                decision="rolled_back", lesson="",
            )
            report = store.report()
            self.assertNotIn("unknown", report["cycles_by_decision"])


class CycleScripts:
    """Helpers to build scripted responses and develop results for a cycle."""

    @staticmethod
    def identify(weakness="A hash algorithm weakness.", location="selfmodel.py",
                 why="It weakens audit integrity.", fix="Use sha256.",
                 confidence=0.7, will_pass=0.6):
        return json_response({
            "weakness": weakness, "location": location, "why_it_matters": why,
            "proposed_fix": fix, "fix_confidence": confidence, "fix_will_pass": will_pass,
        })

    @staticmethod
    def applied(files=None, model_note="Applied a safer hash.", checkpoint_id="cp-1"):
        files = files or [{"path": "src/babymind/selfmodel.py", "bytes_before": 100,
                           "bytes_after": 120, "created": False}]
        return {
            "status": "applied", "attempts": 1, "history": [],
            "result": {
                "status": "applied", "checkpoint_id": checkpoint_id,
                "files": files, "model_note": model_note,
            },
            "notice": "Applied and verified.",
        }

    @staticmethod
    def unrepaired(model_note="Could not fix it.", checkpoint_id="cp-1"):
        files = [{"path": "src/babymind/selfmodel.py", "bytes_before": 100,
                  "bytes_after": 120, "created": False}]
        return {
            "status": "unrepaired", "attempts": 2, "history": [],
            "result": {
                "status": "rolled_back", "checkpoint_id": checkpoint_id,
                "files": files, "model_note": model_note,
            },
            "notice": "Rolled back.",
        }

    @staticmethod
    def evaluate_effective(reasoning="The fix replaces the weak hash with sha256."):
        return json_response({"effective": True, "reasoning": reasoning, "residual_risk": ""})

    @staticmethod
    def evaluate_ineffective(reasoning="The fix changes a constant but does not address the algorithm."):
        return json_response({"effective": False, "reasoning": reasoning, "residual_risk": "Weakness persists."})

    @staticmethod
    def lesson(text="The fix worked."):
        return json_response({"lesson": text})


class LearningCycleTests(unittest.TestCase):
    def _make(self, tmp, selfmodel=None):
        """Create an Independence (which now includes learning) and SelfModel."""
        ind = Independence(home=tmp)
        sm = selfmodel if selfmodel is not None else SelfModel(tmp / "selfmodel.sqlite3")
        # The Independence object now has .learning_store and .learning
        store = ind.learning_store
        cycle = ind.learning
        # Attach the selfmodel so predictions are recorded
        cycle.selfmodel = sm
        return cycle, ind, store, sm

    def test_full_cycle_kept(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            provider = ScriptedProvider([
                CycleScripts.identify(),
                CycleScripts.evaluate_effective(),
                CycleScripts.lesson("The fix works."),
            ])
            fake = ScriptedDevelop([CycleScripts.applied()])
            with mock.patch("babymind.coding_engine.develop", new=fake):
                result = cycle.run_cycle(provider)
            self.assertEqual(result["decision"], "kept")
            self.assertEqual(result["fix_status"], "applied")
            self.assertTrue(result["evaluation"]["effective"])
            # The weakness status is updated.
            weaknesses = store.weaknesses()
            self.assertEqual(weaknesses[0]["status"], "addressed")
            # A position is recorded for the improvement.
            self.assertGreaterEqual(len(ind.positions.positions()), 1)
            # The prediction is resolved as correct (calibration report shows no pending).
            report = sm.calibration_report()
            self.assertEqual(report.get("pending", report.get("unresolved", 0)), 0)
            # A cycle is recorded with the lesson.
            cycles = store.cycles()
            self.assertEqual(len(cycles), 1)
            self.assertEqual(cycles[0]["decision"], "kept")
            self.assertTrue(cycles[0]["effective"])

    def test_full_cycle_verification_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            provider = ScriptedProvider([
                CycleScripts.identify(),
                CycleScripts.lesson("Fix did not pass verification."),
            ])
            fake = ScriptedDevelop([CycleScripts.unrepaired()])
            with mock.patch("babymind.coding_engine.develop", new=fake):
                result = cycle.run_cycle(provider)
            self.assertEqual(result["decision"], "rolled_back")
            self.assertEqual(result["fix_status"], "unrepaired")
            self.assertFalse(result["evaluation"]["effective"])
            # Prediction resolved (calibration report shows no pending).
            report = sm.calibration_report()
            self.assertEqual(report.get("pending", report.get("unresolved", 0)), 0)
            # Weakness status is unaddressed.
            self.assertEqual(store.weaknesses()[0]["status"], "unaddressed")

    def test_full_cycle_ineffective_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            provider = ScriptedProvider([
                CycleScripts.identify(),
                CycleScripts.evaluate_ineffective(),
                CycleScripts.lesson("Tests passed but fix did not address the weakness."),
            ])
            fake = ScriptedDevelop([CycleScripts.applied(checkpoint_id="cp-1")])
            with mock.patch("babymind.coding_engine.develop", new=fake), \
                 mock.patch("babymind.learning.selfdev.rollback") as mock_rollback:
                result = cycle.run_cycle(provider)
            self.assertEqual(result["decision"], "rolled_back")
            self.assertEqual(result["fix_status"], "applied")
            self.assertFalse(result["evaluation"]["effective"])
            # The checkpoint is rolled back because the fix is ineffective.
            mock_rollback.assert_called_once_with(
                "cp-1", agent_id="BM-03", require_permission=False,
            )
            # No position is recorded for an ineffective fix.
            self.assertEqual(len(ind.positions.positions()), 0)

    def test_no_weakness_identified(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            provider = ScriptedProvider([
                json_response({"weakness": "", "location": "", "why_it_matters": "",
                               "proposed_fix": "", "fix_confidence": 0.0, "fix_will_pass": 0.0}),
            ])
            fake = ScriptedDevelop([])
            with mock.patch("babymind.coding_engine.develop", new=fake):
                result = cycle.run_cycle(provider)
            self.assertEqual(result["decision"], "no_change")
            self.assertEqual(store.weaknesses(), [])
            self.assertEqual(store.cycles(), [])

    def test_identify_no_source_returns_no_weakness(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            provider = ScriptedProvider([])
            with mock.patch("babymind.learning.selfdev.dev_root") as mock_dev_root:
                mock_dev_root.side_effect = Exception("No dev root.")
                result = cycle.identify_weakness(provider)
            self.assertEqual(result.get("weakness"), "")
            self.assertEqual(provider.calls, [])

    def test_evaluation_degraded_returns_ineffective(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            provider = ScriptedProvider([
                CycleScripts.identify(),
                "not valid json at all",
                CycleScripts.lesson("Evaluation degraded."),
            ])
            fake = ScriptedDevelop([CycleScripts.applied(checkpoint_id="cp-1")])
            with mock.patch("babymind.coding_engine.develop", new=fake), \
                 mock.patch("babymind.learning.selfdev.rollback") as mock_rollback:
                result = cycle.run_cycle(provider)
            self.assertEqual(result["decision"], "rolled_back")
            self.assertFalse(result["evaluation"]["effective"])
            mock_rollback.assert_called_once()

    def test_run_multiple_cycles(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            provider = ScriptedProvider([
                CycleScripts.identify(weakness="Weakness A."),
                CycleScripts.evaluate_effective(),
                CycleScripts.lesson("A fixed."),
                CycleScripts.identify(weakness="Weakness B."),
                CycleScripts.evaluate_effective(),
                CycleScripts.lesson("B fixed."),
            ])
            fake = ScriptedDevelop([
                CycleScripts.applied(checkpoint_id="cp-1"),
                CycleScripts.applied(checkpoint_id="cp-2"),
            ])
            with mock.patch("babymind.coding_engine.develop", new=fake):
                result = cycle.run(provider, cycles=2)
            self.assertEqual(result["cycles_requested"], 2)
            self.assertEqual(len(result["cycles"]), 2)
            self.assertEqual(result["decisions"]["kept"], 2)
            self.assertEqual(len(store.cycles()), 2)

    def test_run_rejects_out_of_range(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            with self.assertRaises(ValueError):
                cycle.run(ScriptedProvider([]), cycles=0)
            with self.assertRaises(ValueError):
                cycle.run(ScriptedProvider([]), cycles=11)

    def test_develop_failure_records_failed_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            provider = ScriptedProvider([
                CycleScripts.identify(),
                CycleScripts.lesson("Develop crashed."),
            ])

            def raising_develop(provider_arg, task, *, attempts=2, **kwargs):
                raise RuntimeError("engine exploded")

            with mock.patch("babymind.coding_engine.develop", new=raising_develop):
                result = cycle.run_cycle(provider)
            self.assertEqual(result["decision"], "failed")
            self.assertEqual(result["fix_status"], "failed")

    def test_status_reports_store(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            status = cycle.status()
            self.assertIn("learning", status)
            self.assertIn("cycles_total", status["learning"])

    def test_position_not_recorded_when_rolled_back(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            provider = ScriptedProvider([
                CycleScripts.identify(),
                CycleScripts.evaluate_ineffective(),
                CycleScripts.lesson("Ineffective."),
            ])
            fake = ScriptedDevelop([CycleScripts.applied(checkpoint_id="cp-1")])
            with mock.patch("babymind.coding_engine.develop", new=fake), \
                 mock.patch("babymind.learning.selfdev.rollback"):
                result = cycle.run_cycle(provider)
            self.assertEqual(result["decision"], "rolled_back")
            self.assertEqual(len(ind.positions.positions()), 0)

    def test_daemon_state_is_durable(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = _make_store(tmp)
            store.set_daemon_state(state="paused", total_cycles=3, last_error="transient")
            reopened = _make_store(tmp)
            state = reopened.daemon_state()
            self.assertEqual(state["state"], "paused")
            self.assertEqual(state["total_cycles"], 3)
            self.assertEqual(state["last_error"], "transient")
            self.assertTrue(reopened.verify_audit_chain()["intact"])

    def test_edit_guard_protects_supervisor_and_verification(self):
        from babymind.learning import learning_edit_guard
        self.assertIsNone(learning_edit_guard("src/babymind/response_quality.py"))
        for path in ("src/babymind/learning.py", "src/babymind/learning_service.py",
                     "src/babymind/selfdev.py", "src/babymind/web/app.js",
                     "tests/test_learning.py", "../outside.py", ".github/workflows/tests.yml"):
            with self.subTest(path=path):
                self.assertTrue(learning_edit_guard(path))

    def test_weakness_attempts_retire_repeated_failures(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            weakness = store.record_weakness("A recurring weakness.")
            for _ in range(3):
                store.note_weakness_attempt(weakness["id"], decision="rolled_back")
            loaded = store.weakness(weakness["id"])
            self.assertEqual(loaded["attempts"], 3)
            self.assertEqual(loaded["status"], "dismissed")
            self.assertNotIn(weakness["id"], [w["id"] for w in store.weaknesses("unaddressed")])
            self.assertTrue(store.verify_audit_chain()["intact"])

    def test_autonomous_work_retries_backlog_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            backlog = store.record_weakness("An unresolved weakness.")
            store.set_weakness_status(backlog["id"], "unaddressed")
            provider = ScriptedProvider([])
            work = cycle.select_autonomous_work(provider)
            self.assertEqual(work["kind"], "retry")
            self.assertEqual(work["weakness_id"], backlog["id"])
            self.assertEqual(provider.calls, [])

            store.set_weakness_status(backlog["id"], "addressed")
            addressed = store.record_weakness("A hash algorithm weakness.")
            store.set_weakness_status(addressed["id"], "addressed")
            provider = ScriptedProvider([CycleScripts.identify()])
            duplicate = cycle.select_autonomous_work(provider)
            self.assertEqual(duplicate["kind"], "no_work")
            self.assertIn("already", duplicate["reason"])

            provider = ScriptedProvider([CycleScripts.identify(weakness="A brand new weakness.")])
            fresh = cycle.select_autonomous_work(provider)
            self.assertEqual(fresh["kind"], "new")
            self.assertEqual(len(provider.calls), 1)

    def test_autonomous_cycle_passes_edit_guard(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            weakness = store.record_weakness("A durable weakness.", prediction_confidence=0.7)
            provider = ScriptedProvider([
                CycleScripts.evaluate_effective(), CycleScripts.lesson("Worked."),
            ])
            fake = ScriptedDevelop([CycleScripts.applied()])
            with mock.patch("babymind.coding_engine.develop", new=fake):
                result = cycle.run_autonomous_cycle(provider)
            self.assertEqual(result["decision"], "kept")
            self.assertEqual(result["autonomous_work"], "retry")
            self.assertTrue(callable(fake.calls[0]["edit_guard"]))
            self.assertIn("src/babymind", fake.calls[0]["task"])
            loaded = store.weakness(weakness["id"])
            self.assertEqual(loaded["status"], "addressed")
            self.assertEqual(loaded["attempts"], 1)

    def test_evaluation_reads_the_verified_transaction_files(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            fix = CycleScripts.applied(files=[{"path": "src/babymind/response_quality.py"}])
            provider = ScriptedProvider([CycleScripts.evaluate_effective()])
            with mock.patch.object(cycle, "_read_changed_files", return_value="code") as reader:
                result = cycle.evaluate_fix(provider, {"weakness": "A bug."}, fix)
            self.assertTrue(result["effective"])
            reader.assert_called_once_with(["src/babymind/response_quality.py"])

    def test_status_reports_default_on_supervisor(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cycle, ind, store, sm = self._make(tmp)
            status = cycle.status()
            self.assertTrue(status["autonomous"]["default_enabled"])
            self.assertEqual(status["autonomous"]["process_state"], "not_started_in_this_process")
            self.assertIn("supervisor", status["learning"])

            class FakeDaemon:
                def status(self):
                    return {"state": "idle", "default_enabled": True}
            cycle.daemon = FakeDaemon()
            self.assertEqual(cycle.status()["autonomous"]["state"], "idle")


if __name__ == "__main__":
    unittest.main()
