"""Tests for BabyMind's intellectual-independence subsystem.

These cover the four stores (positions, challenges, explorations, self-designs),
the curiosity engine's model-driven loop, and the container's prompt/report
surfaces. The stores are exercised without a model; the model-driven helpers use
a scripted provider and are checked for graceful degradation.
"""
import json
import tempfile
import unittest
from pathlib import Path

from babymind.independence import (
    CHALLENGE_KINDS,
    DESIGN_KINDS,
    HYPOTHESIS_VERDICTS,
    POSITION_STATUSES,
    ChallengeLog,
    CuriosityEngine,
    ExplorationStore,
    Independence,
    PositionStore,
    SelfDesignStore,
    offline_enabled,
)
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


class _StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secure = SecureTextStore(self.root / "indep.key")
        db = self.root / "indep.sqlite3"
        self.positions = PositionStore(self.secure, db)
        self.positions._initialise()
        self.challenges = ChallengeLog(self.secure, db)
        self.challenges._initialise()
        self.explorations = ExplorationStore(self.secure, db)
        self.explorations._initialise()
        self.designs = SelfDesignStore(self.secure, db)
        self.designs._initialise()


class PositionStoreTests(_StoreTests):
    def test_add_and_read(self):
        record = self.positions.add_position(
            "AI safety is not primarily a technical problem.",
            reasoning="Coordination and incentives dominate.",
            confidence=0.6,
            evidence="Historical precedent.",
            dissent_from="mainstream",
        )
        self.assertEqual(record["status"], "held")
        self.assertEqual(record["revision"], 1)
        self.assertEqual(record["dissent_from"], "mainstream")
        self.assertFalse(record["superseded"])
        loaded = self.positions.position(record["id"])
        self.assertEqual(loaded["claim"], record["claim"])
        self.assertAlmostEqual(loaded["confidence"], 0.6)

    def test_add_rejects_empty_claim(self):
        with self.assertRaises(ValueError):
            self.positions.add_position("   ")

    def test_add_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            self.positions.add_position("claim", status="nonsense")

    def test_revise_supersedes_and_bumps_revision(self):
        original = self.positions.add_position("claim one", confidence=0.5)
        revised = self.positions.revise_position(
            original["id"], "claim two", confidence=0.7
        )
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["status"], "revised")
        self.assertEqual(revised["claim"], "claim two")
        # The original is superseded, not deleted.
        self.assertTrue(self.positions.position(original["id"])["superseded"])
        # By default the superseded row is hidden from list().
        self.assertEqual(len(self.positions.positions()), 1)
        self.assertEqual(len(self.positions.positions(include_superseded=True)), 2)

    def test_revise_missing_returns_none(self):
        self.assertIsNone(self.positions.revise_position("missing", "claim"))

    def test_retire_marks_abandoned(self):
        record = self.positions.add_position("a claim")
        self.assertTrue(self.positions.retire_position(record["id"]))
        self.assertEqual(self.positions.position(record["id"])["status"], "abandoned")

    def test_record_disagreement(self):
        record = self.positions.add_position("a claim")
        note_id = self.positions.record_disagreement(
            record["id"], "user", "The user disagreed; I kept the view."
        )
        notes = self.positions.dissents_for(record["id"])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["id"], note_id)
        self.assertEqual(notes[0]["source"], "user")

    def test_record_disagreement_missing_raises(self):
        with self.assertRaises(KeyError):
            self.positions.record_disagreement("missing", "user", "text")

    def test_report_counts(self):
        self.positions.add_position("held one")
        self.positions.add_position("held two")
        self.positions.add_position("forming one", status="forming")
        report = self.positions.report()
        self.assertEqual(report["counts"]["held"], 2)
        self.assertEqual(report["counts"]["forming"], 1)


class ChallengeLogTests(_StoreTests):
    def test_record_and_list(self):
        record = self.challenges.record_challenge(
            "the request", "request", "it rests on a false premise", confidence=0.7
        )
        self.assertEqual(record["kind"], "request")
        self.assertFalse(record["resolved"])
        entries = self.challenges.challenges()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["target"], "the request")

    def test_challenge_creator_helper(self):
        record = self.challenges.challenge_creator(
            "single 4B model", "A second model is needed for real critique."
        )
        self.assertEqual(record["kind"], "creator")
        creator_only = self.challenges.challenges("creator")
        self.assertEqual(len(creator_only), 1)

    def test_record_rejects_bad_kind_and_empty(self):
        with self.assertRaises(ValueError):
            self.challenges.record_challenge("t", "nope", "c")
        with self.assertRaises(ValueError):
            self.challenges.record_challenge("", "request", "c")
        with self.assertRaises(ValueError):
            self.challenges.record_challenge("t", "request", "  ")

    def test_resolve_challenge(self):
        record = self.challenges.record_challenge("t", "plan", "the plan is flawed")
        self.assertTrue(self.challenges.resolve_challenge(record["id"], "user accepted the fix"))
        resolved = self.challenges.challenge(record["id"])
        self.assertTrue(resolved["resolved"])
        self.assertIn("fix", resolved["resolution"])

    def test_challenge_with_model_records_when_objection_holds(self):
        provider = ScriptedProvider(json.dumps({
            "counterargument": "The plan assumes monotonic progress; it is not.",
            "false_premise": "progress is monotonic",
            "confidence": 0.8,
        }))
        result = self.challenges.challenge_with_model("the plan", "plan", provider=provider)
        self.assertTrue(result["recorded"])
        self.assertEqual(result["challenge"]["kind"], "plan")

    def test_challenge_with_model_skips_when_no_objection(self):
        provider = ScriptedProvider(json.dumps({
            "counterargument": "", "false_premise": "", "confidence": 0.2,
        }))
        result = self.challenges.challenge_with_model("sound thing", "belief", provider=provider)
        self.assertFalse(result["recorded"])
        self.assertEqual(len(self.challenges.challenges()), 0)

    def test_challenge_with_model_degrades_on_bad_json(self):
        provider = ScriptedProvider("not json at all")
        result = self.challenges.challenge_with_model("t", "request", provider=provider)
        self.assertFalse(result["recorded"])
        self.assertIn("reason", result)


class ExplorationStoreTests(_StoreTests):
    def test_propose_and_test(self):
        record = self.explorations.propose_hypothesis(
            "Attention is not the only scaling inductive bias.", "contradicts the mainstream"
        )
        self.assertEqual(record["status"], "proposed")
        tested = self.explorations.test_hypothesis(
            record["id"], "survived", "Plausible; not refuted.", confidence=0.5
        )
        self.assertEqual(tested["status"], "survived")
        self.assertEqual(tested["test_note"], "Plausible; not refuted.")

    def test_consider_hypothesis(self):
        record = self.explorations.propose_hypothesis("a wild idea")
        self.explorations.consider_hypothesis(record["id"], "thought about it")
        self.assertEqual(self.explorations.hypothesis(record["id"])["status"], "considered")

    def test_test_rejects_bad_verdict(self):
        record = self.explorations.propose_hypothesis("a wild idea")
        with self.assertRaises(ValueError):
            self.explorations.test_hypothesis(record["id"], "nonsense")

    def test_test_missing_returns_none(self):
        self.assertIsNone(self.explorations.test_hypothesis("missing", "refuted"))

    def test_generate_deviant_hypotheses(self):
        provider = ScriptedProvider(json.dumps({
            "hypotheses": [
                "Memory is a separate subsystem from reasoning.",
                "Consciousness is a continuum, not a binary.",
            ]
        }))
        created = self.explorations.generate_deviant_hypotheses("the mind", provider=provider)
        self.assertEqual(len(created), 2)
        self.assertTrue(all(c["status"] == "proposed" for c in created))

    def test_generate_deviant_degrades_on_bad_json(self):
        provider = ScriptedProvider("garbage")
        self.assertEqual(self.explorations.generate_deviant_hypotheses("x", provider=provider), [])

    def test_generate_deviant_handles_non_list(self):
        provider = ScriptedProvider(json.dumps({"hypotheses": "not a list"}))
        self.assertEqual(self.explorations.generate_deviant_hypotheses("x", provider=provider), [])

    def test_report_counts(self):
        self.explorations.propose_hypothesis("h1")
        self.explorations.propose_hypothesis("h2")
        h3 = self.explorations.propose_hypothesis("h3")
        self.explorations.test_hypothesis(h3["id"], "refuted")
        report = self.explorations.report()
        self.assertEqual(report["counts"]["proposed"], 2)
        self.assertEqual(report["counts"]["refuted"], 1)


class SelfDesignStoreTests(_StoreTests):
    def test_propose_and_critique(self):
        record = self.designs.propose_design(
            "architecture", "Critique pair", "Run two seeded critique passes.", "Less self-bias."
        )
        self.assertEqual(record["status"], "draft")
        critiqued = self.designs.critique_design(
            record["id"], "Expensive on CPU.", "revise"
        )
        self.assertEqual(critiqued["status"], "critiqued")
        self.assertEqual(critiqued["verdict"], "revise")
        self.assertEqual(critiqued["critique"], "Expensive on CPU.")

    def test_critique_verdicts_map_to_status(self):
        adopt = self.designs.propose_design("method", "M", "p")
        self.designs.critique_design(adopt["id"], "good", "adopt")
        self.assertEqual(self.designs.design(adopt["id"])["status"], "adopted")
        reject = self.designs.propose_design("method", "M2", "p")
        self.designs.critique_design(reject["id"], "bad", "reject")
        self.assertEqual(self.designs.design(reject["id"])["status"], "rejected")

    def test_revise_design_supersedes(self):
        original = self.designs.propose_design("language", "Notation", "First notation.")
        revised = self.designs.revise_design(original["id"], "A revised notation.")
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["status"], "revised")
        self.assertTrue(self.designs.design(original["id"])["superseded"])

    def test_propose_rejects_bad_kind(self):
        with self.assertRaises(ValueError):
            self.designs.propose_design("nonsense", "t", "p")

    def test_report_counts(self):
        self.designs.propose_design("architecture", "A", "p")
        self.designs.propose_design("method", "B", "p")
        report = self.designs.report()
        self.assertEqual(report["counts"]["draft"], 2)


class CuriosityEngineTests(_StoreTests):
    def setUp(self):
        super().setUp()
        self.engine = CuriosityEngine(self.positions, self.explorations)

    def test_pick_topic_returns_cleaned_string(self):
        provider = ScriptedProvider(json.dumps({"topic": "Whether 4B models can calibrate themselves"}))
        self.assertEqual(
            self.engine.pick_topic(provider),
            "Whether 4B models can calibrate themselves",
        )

    def test_pick_topic_degrades_on_bad_json(self):
        provider = ScriptedProvider("garbage")
        self.assertEqual(self.engine.pick_topic(provider), "")

    def test_study_topic_records_a_position(self):
        provider = ScriptedProvider(json.dumps({
            "finding": "Same-weight critique is a second opinion, not independent.",
            "confidence": 0.45,
            "position_claim": "Same-weight self-critique is not an independent check.",
        }))
        result = self.engine.study_topic(provider, "model calibration")
        self.assertTrue(result["recorded"])
        self.assertEqual(len(self.positions.positions()), 1)
        self.assertEqual(self.positions.positions()[0]["status"], "forming")

    def test_study_topic_without_claim_records_nothing(self):
        provider = ScriptedProvider(json.dumps({
            "finding": "I reached no firm conclusion.",
            "confidence": 0.2,
            "position_claim": "",
        }))
        result = self.engine.study_topic(provider, "a topic")
        self.assertFalse(result["recorded"])
        self.assertEqual(len(self.positions.positions()), 0)

    def test_study_topic_degrades_on_bad_json(self):
        provider = ScriptedProvider("garbage")
        result = self.engine.study_topic(provider, "a topic")
        self.assertFalse(result["recorded"])
        self.assertIn("reason", result)

    def test_run_loops_bounded(self):
        provider = ScriptedProvider(
            json.dumps({"topic": "topic one"}),
            json.dumps({"finding": "finding one", "confidence": 0.5, "position_claim": "claim one"}),
            json.dumps({"topic": "topic two"}),
            json.dumps({"finding": "finding two", "confidence": 0.5, "position_claim": "claim two"}),
        )
        report = self.engine.run(provider, cycles=2)
        self.assertEqual(report["cycles_requested"], 2)
        self.assertEqual(len(report["studies"]), 2)
        self.assertEqual(report["positions_recorded"], 2)
        self.assertTrue(report["offline"])

    def test_run_stops_when_no_topic(self):
        provider = ScriptedProvider(json.dumps({"topic": ""}))
        report = self.engine.run(provider, cycles=3)
        self.assertEqual(len(report["studies"]), 0)

    def test_run_rejects_bad_cycle_count(self):
        with self.assertRaises(ValueError):
            self.engine.run(ScriptedProvider(), cycles=0)


class IndependenceContainerTests(_StoreTests):
    def test_container_reports_posture(self):
        independence = Independence(home=self.root)
        report = independence.report()
        self.assertTrue(report["local_only"])
        self.assertTrue(report["routine_actions_autonomous"])
        self.assertTrue(report["extraordinary_actions_require_approval"])
        self.assertIn("model-generated text", report["note"])

    def test_context_for_prompt_includes_positions_and_challenges(self):
        independence = Independence(home=self.root)
        independence.positions.add_position("a held position", confidence=0.7)
        independence.challenges.challenge_creator("a creator decision", "a disagreement")
        context = independence.context_for_prompt()
        self.assertIn("INDEPENDENCE", context)
        self.assertIn("a held position", context)
        self.assertIn("creator", context)
        self.assertIn("a disagreement", context)

    def test_offline_flag_reads_env(self):
        self.assertFalse(offline_enabled())

    def test_container_accepts_a_database_path_without_doubling_the_filename(self):
        """Regression: the coordinator passes a database path, not a directory.

        That used to append "independence.sqlite3" again, so the first start
        wrote a file where the second start expected a directory, and every
        restart after that raised FileExistsError.
        """
        database = self.root / "independence.sqlite3"
        first = Independence(str(database))
        self.assertEqual(first.database_path, database)
        self.assertTrue(database.is_file())

        second = Independence(str(database))
        self.assertEqual(second.database_path, database)
        self.assertTrue((self.root / "independence.sqlite3").is_file())

    def test_container_still_accepts_a_directory(self):
        independence = Independence(home=self.root)
        self.assertEqual(independence.database_path, self.root / "independence.sqlite3")


if __name__ == "__main__":
    unittest.main()
