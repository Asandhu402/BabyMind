"""Tests for BabyMind's evidence-gathering and experimental learning loop.

These cover the EvidenceStore (evidence records, test records, hash-chained
audit), the EvidenceLoop's model-driven design/evaluate stages (with a scripted
provider and graceful degradation), and the full test_position / test_hypothesis
/ run loops. The evidence gathering is exercised without a real network or
sandbox where possible; the code-experiment path is tested with a stubbed broker
so the test does not depend on kernel namespace support.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import babymind.broker  # noqa: F401 - ensure the submodule attribute exists for patch()
import babymind.runner  # noqa: F401

from babymind.evidence import (
    EVIDENCE_KINDS,
    VERDICTS,
    EvidenceLoop,
    EvidenceStore,
)
from babymind.independence import (
    ExplorationStore,
    Independence,
    PositionStore,
)
from babymind.selfmodel import SelfModel
from babymind.secure_store import SecureTextStore


class ScriptedProvider:
    """Returns queued replies in order; records what it was asked."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.system_prompts = []
        self.user_prompts = []

    def complete(self, system_prompt, user_prompt):
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
        if not self.replies:
            raise AssertionError("ScriptedProvider ran out of replies.")
        return self.replies.pop(0)


class _EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secure = SecureTextStore(self.root / "indep.key")
        db = self.root / "indep.sqlite3"
        self.positions = PositionStore(self.secure, db)
        self.positions._initialise()
        self.explorations = ExplorationStore(self.secure, db)
        self.explorations._initialise()
        self.evidence_store = EvidenceStore(self.secure, db)
        self.evidence_store._initialise()
        self.selfmodel = SelfModel(self.root / "selfmodel.sqlite3")
        self.loop = EvidenceLoop(
            self.positions, self.explorations, self.evidence_store,
            selfmodel=self.selfmodel, home=self.root,
        )


class EvidenceStoreTests(_EvidenceTests):
    def test_record_and_read_evidence(self):
        record = self.evidence_store.record_evidence(
            target="a claim", claim="a claim", kind="web_search",
            source_detail="title — url", raw_output="snippet text",
        )
        self.assertEqual(record["kind"], "web_search")
        self.assertEqual(record["raw_output"], "snippet text")
        self.assertIsNone(record["exit_code"])
        loaded = self.evidence_store.evidence(record["id"])
        self.assertEqual(loaded["source_detail"], "title — url")

    def test_record_evidence_rejects_bad_kind(self):
        with self.assertRaises(ValueError):
            self.evidence_store.record_evidence(
                target="t", claim="c", kind="nonsense", source_detail="s", raw_output="o",
            )

    def test_record_and_read_test(self):
        test = self.evidence_store.record_test(
            position_id="p1", claim="a claim",
            design={"kind": "web_search", "query": "q"},
            evidence_ids=["e1"], verdict="supported", confidence=0.8,
            reasoning="evidence supports", what_changed="raised confidence",
            prediction_id="pred1", prediction_outcome="correct",
        )
        self.assertEqual(test["verdict"], "supported")
        self.assertEqual(test["design"]["kind"], "web_search")
        self.assertEqual(test["evidence_ids"], ["e1"])
        self.assertEqual(test["prediction_outcome"], "correct")

    def test_record_test_rejects_bad_verdict(self):
        with self.assertRaises(ValueError):
            self.evidence_store.record_test(
                claim="c", design={}, evidence_ids=[], verdict="nonsense",
                confidence=0.5, reasoning="r", what_changed="w",
            )

    def test_audit_chain_tamper_detection(self):
        self.evidence_store.audit("test", {"claim": "c"})
        self.assertTrue(self.evidence_store.verify_audit_chain()["intact"])
        # Tamper with the audit table directly.
        import sqlite3
        conn = sqlite3.connect(self.root / "indep.sqlite3")
        conn.execute("UPDATE independence_audit SET payload='tampered' WHERE seq=1")
        conn.commit()
        conn.close()
        self.assertFalse(self.evidence_store.verify_audit_chain()["intact"])

    def test_report_counts(self):
        self.evidence_store.record_evidence(
            target="t", claim="c", kind="web_search", source_detail="s", raw_output="o",
        )
        self.evidence_store.record_test(
            claim="c", design={}, evidence_ids=[], verdict="supported",
            confidence=0.8, reasoning="r", what_changed="w",
        )
        report = self.evidence_store.report()
        self.assertEqual(report["tests_total"], 1)
        self.assertEqual(report["tests_by_verdict"]["supported"], 1)
        self.assertEqual(report["evidence_by_kind"]["web_search"], 1)


class DesignTestTests(_EvidenceTests):
    def test_design_web_search(self):
        provider = ScriptedProvider(json.dumps({
            "kind": "web_search", "query": "scaling laws",
            "expected": "find counterevidence", "reasoning": "literature search",
        }))
        design = self.loop.design_test(provider, "attention scales")
        self.assertEqual(design["kind"], "web_search")
        self.assertEqual(design["query"], "scaling laws")

    def test_design_code_experiment(self):
        provider = ScriptedProvider(json.dumps({
            "kind": "code_experiment", "command": "print(1+1)",
            "expected": "prints 2", "reasoning": "arithmetic check",
        }))
        design = self.loop.design_test(provider, "1+1=2")
        self.assertEqual(design["kind"], "code_experiment")
        self.assertEqual(design["command"], "print(1+1)")

    def test_design_rejects_bad_kind(self):
        provider = ScriptedProvider(json.dumps({"kind": "nonsense", "query": "q"}))
        design = self.loop.design_test(provider, "a claim")
        self.assertEqual(design["kind"], "")

    def test_design_rejects_web_search_without_query(self):
        provider = ScriptedProvider(json.dumps({"kind": "web_search", "query": ""}))
        design = self.loop.design_test(provider, "a claim")
        self.assertEqual(design["kind"], "")

    def test_design_degrades_on_bad_json(self):
        provider = ScriptedProvider("garbage")
        design = self.loop.design_test(provider, "a claim")
        self.assertEqual(design["kind"], "")


class EvaluateTests(_EvidenceTests):
    def _evidence(self, output="some evidence"):
        return [self.evidence_store.record_evidence(
            target="c", claim="c", kind="web_search",
            source_detail="s", raw_output=output,
        )]

    def test_evaluate_supported(self):
        provider = ScriptedProvider(json.dumps({
            "verdict": "supported", "confidence": 0.8,
            "reasoning": "evidence confirms", "what_would_settle_it": "",
        }))
        result = self.loop.evaluate(provider, "a claim", self._evidence())
        self.assertEqual(result["verdict"], "supported")
        self.assertAlmostEqual(result["confidence"], 0.8)

    def test_evaluate_refuted(self):
        provider = ScriptedProvider(json.dumps({
            "verdict": "refuted", "confidence": 0.7,
            "reasoning": "evidence contradicts", "what_would_settle_it": "",
        }))
        result = self.loop.evaluate(provider, "a claim", self._evidence())
        self.assertEqual(result["verdict"], "refuted")

    def test_evaluate_invalid_verdict_defaults_to_unclear(self):
        provider = ScriptedProvider(json.dumps({
            "verdict": "nonsense", "confidence": 0.5, "reasoning": "r", "what_would_settle_it": "",
        }))
        result = self.loop.evaluate(provider, "a claim", self._evidence())
        self.assertEqual(result["verdict"], "unclear")

    def test_evaluate_no_evidence_is_inconclusive(self):
        provider = ScriptedProvider()
        result = self.loop.evaluate(provider, "a claim", [])
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(len(provider.system_prompts), 0)

    def test_evaluate_degrades_on_bad_json(self):
        provider = ScriptedProvider("garbage")
        result = self.loop.evaluate(provider, "a claim", self._evidence())
        self.assertEqual(result["verdict"], "inconclusive")


class TestPositionTests(_EvidenceTests):
    def test_position_supported_raises_confidence(self):
        position = self.positions.add_position("a claim", confidence=0.6)
        provider = ScriptedProvider(
            json.dumps({"kind": "code_experiment", "command": "print(1)"}),
            json.dumps({"verdict": "supported", "confidence": 0.8, "reasoning": "ok", "what_would_settle_it": ""}),
        )
        # Stub the broker so no real sandbox is needed.
        with patch("babymind.broker") as mock_broker, \
             patch("babymind.runner") as mock_runner:
            mock_runner.venv_python.return_value = "/usr/bin/python3"
            mock_broker.execute.return_value = {
                "stdout": "1", "stderr": "", "exit_code": 0,
            }
            result = self.loop.test_position(provider, position["id"], allow_experiments=True)
        self.assertEqual(result["evaluation"]["verdict"], "supported")
        self.assertGreater(result["updated_position"]["confidence"], 0.6)
        self.assertEqual(result["prediction_outcome"], "correct")

    def test_position_refuted_lowers_confidence_and_revises(self):
        position = self.positions.add_position("a claim", confidence=0.7)
        provider = ScriptedProvider(
            json.dumps({"kind": "code_experiment", "command": "print(0)"}),
            json.dumps({"verdict": "refuted", "confidence": 0.8, "reasoning": "contradicted", "what_would_settle_it": ""}),
        )
        with patch("babymind.broker") as mock_broker, \
             patch("babymind.runner") as mock_runner:
            mock_runner.venv_python.return_value = "/usr/bin/python3"
            mock_broker.execute.return_value = {
                "stdout": "0", "stderr": "", "exit_code": 0,
            }
            result = self.loop.test_position(provider, position["id"], allow_experiments=True)
        self.assertEqual(result["evaluation"]["verdict"], "refuted")
        self.assertLess(result["updated_position"]["confidence"], 0.7)
        self.assertEqual(result["prediction_outcome"], "incorrect")
        # The original is superseded by the revision.
        self.assertTrue(self.positions.position(position["id"])["superseded"])

    def test_position_inconclusive_no_change(self):
        position = self.positions.add_position("a claim", confidence=0.5)
        provider = ScriptedProvider(
            json.dumps({"kind": "web_search", "query": "q"}),
            json.dumps({"verdict": "inconclusive", "confidence": 0.3, "reasoning": "no evidence", "what_would_settle_it": ""}),
        )
        # Web not enabled -> local_reasoning evidence, no real network call.
        result = self.loop.test_position(provider, position["id"], allow_web=False)
        self.assertEqual(result["evaluation"]["verdict"], "inconclusive")
        self.assertAlmostEqual(result["updated_position"]["confidence"], 0.5)
        self.assertEqual(result["prediction_outcome"], "unverified")

    def test_position_not_found_raises(self):
        with self.assertRaises(KeyError):
            self.loop.test_position(ScriptedProvider(), "missing")

    def test_prediction_feeds_calibration(self):
        position = self.positions.add_position("a claim", confidence=0.7)
        provider = ScriptedProvider(
            json.dumps({"kind": "code_experiment", "command": "print(1)"}),
            json.dumps({"verdict": "supported", "confidence": 0.8, "reasoning": "ok", "what_would_settle_it": ""}),
        )
        with patch("babymind.broker") as mock_broker, \
             patch("babymind.runner") as mock_runner:
            mock_runner.venv_python.return_value = "/usr/bin/python3"
            mock_broker.execute.return_value = {"stdout": "1", "stderr": "", "exit_code": 0}
            self.loop.test_position(provider, position["id"], allow_experiments=True)
        cal = self.selfmodel.calibration_report()
        self.assertEqual(cal["scored"], 1)
        self.assertIsNotNone(cal["brier_score"])


class TestHypothesisTests(_EvidenceTests):
    def test_hypothesis_supported_marks_survived(self):
        hypothesis = self.explorations.propose_hypothesis("a hypothesis")
        provider = ScriptedProvider(
            json.dumps({"kind": "code_experiment", "command": "print(1)"}),
            json.dumps({"verdict": "supported", "confidence": 0.8, "reasoning": "ok", "what_would_settle_it": ""}),
        )
        with patch("babymind.broker") as mock_broker, \
             patch("babymind.runner") as mock_runner:
            mock_runner.venv_python.return_value = "/usr/bin/python3"
            mock_broker.execute.return_value = {"stdout": "1", "stderr": "", "exit_code": 0}
            result = self.loop.test_hypothesis(provider, hypothesis["id"], allow_experiments=True)
        self.assertEqual(result["evaluation"]["verdict"], "supported")
        self.assertEqual(result["updated_hypothesis"]["status"], "survived")

    def test_hypothesis_refuted_marks_refuted(self):
        hypothesis = self.explorations.propose_hypothesis("a hypothesis")
        provider = ScriptedProvider(
            json.dumps({"kind": "code_experiment", "command": "print(0)"}),
            json.dumps({"verdict": "refuted", "confidence": 0.8, "reasoning": "contradicted", "what_would_settle_it": ""}),
        )
        with patch("babymind.broker") as mock_broker, \
             patch("babymind.runner") as mock_runner:
            mock_runner.venv_python.return_value = "/usr/bin/python3"
            mock_broker.execute.return_value = {"stdout": "0", "stderr": "", "exit_code": 0}
            result = self.loop.test_hypothesis(provider, hypothesis["id"], allow_experiments=True)
        self.assertEqual(result["updated_hypothesis"]["status"], "refuted")

    def test_hypothesis_inconclusive_marks_undecided(self):
        hypothesis = self.explorations.propose_hypothesis("a hypothesis")
        provider = ScriptedProvider(
            json.dumps({"kind": "web_search", "query": "q"}),
            json.dumps({"verdict": "inconclusive", "confidence": 0.3, "reasoning": "no evidence", "what_would_settle_it": ""}),
        )
        result = self.loop.test_hypothesis(provider, hypothesis["id"], allow_web=False)
        self.assertEqual(result["updated_hypothesis"]["status"], "undecided")

    def test_hypothesis_not_found_raises(self):
        with self.assertRaises(KeyError):
            self.loop.test_hypothesis(ScriptedProvider(), "missing")


class RunTests(_EvidenceTests):
    def test_run_requires_at_least_one_evidence_kind(self):
        with self.assertRaises(ValueError):
            self.loop.run(ScriptedProvider(), cycles=1)

    def test_run_rejects_bad_cycle_count(self):
        with self.assertRaises(ValueError):
            self.loop.run(ScriptedProvider(), cycles=0, allow_experiments=True)

    def test_run_tests_candidates_with_experiments(self):
        self.positions.add_position("a claim", confidence=0.6)
        self.explorations.propose_hypothesis("a hypothesis")
        provider = ScriptedProvider(
            json.dumps({"kind": "code_experiment", "command": "print(1)"}),
            json.dumps({"verdict": "supported", "confidence": 0.8, "reasoning": "ok", "what_would_settle_it": ""}),
            json.dumps({"kind": "code_experiment", "command": "print(1)"}),
            json.dumps({"verdict": "supported", "confidence": 0.8, "reasoning": "ok", "what_would_settle_it": ""}),
        )
        with patch("babymind.broker") as mock_broker, \
             patch("babymind.runner") as mock_runner:
            mock_runner.venv_python.return_value = "/usr/bin/python3"
            mock_broker.execute.return_value = {"stdout": "1", "stderr": "", "exit_code": 0}
            report = self.loop.run(provider, cycles=2, allow_experiments=True)
        self.assertEqual(len(report["tests"]), 2)
        self.assertEqual(report["verdicts"]["supported"], 2)


class ContainerIntegrationTests(unittest.TestCase):
    def test_container_wires_evidence_loop(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        ind = Independence(home=Path(temp.name))
        self.assertTrue(hasattr(ind, "evidence"))
        self.assertTrue(hasattr(ind, "evidence_store"))
        report = ind.report()
        self.assertIn("evidence", report)
        self.assertIn("tests_total", report["evidence"])


if __name__ == "__main__":
    unittest.main()
