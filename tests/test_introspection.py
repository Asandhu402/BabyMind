"""Tests for BabyMind's metacognitive self-review pipeline."""
import json
import tempfile
import unittest
from pathlib import Path

from babymind.coordinator import BabyMindCoordinator
from babymind.introspection import (
    IntrospectionResult,
    independent_thinker_directive,
    run_introspection,
    strip_reflexive_agreement,
)
from babymind.memory import LocalMemory


class ScriptedProvider:
    """Returns queued replies in order and records what it was asked."""

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

    @property
    def calls(self):
        return len(self.system_prompts)


def assessment(**overrides):
    payload = {
        "restated_request": "the question",
        "false_premise": "",
        "what_i_know": ["a fact"],
        "what_i_do_not_know": ["an unknown"],
        "assumptions_required": ["an assumption"],
        "sycophancy_risk": 0.1,
        "should_push_back": False,
        "push_back": "",
        "confidence_before": 0.7,
    }
    payload.update(overrides)
    return json.dumps(payload)


def review(verdict="sound", **overrides):
    payload = {
        "factual_errors": [],
        "unsupported_claims": [],
        "missed_the_question": "",
        "sycophancy": "",
        "overconfidence": "",
        "unclear": [],
        "verdict": verdict,
        "most_important_fix": "",
    }
    payload.update(overrides)
    return json.dumps(payload)


class IntrospectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.memory = LocalMemory(Path(self.temp.name) / "memory.sqlite3")

    def run_pipeline(self, provider, task="A question?", **kwargs):
        return run_introspection(
            provider, task, draft_fn=lambda t, c: "The first draft.", **kwargs
        )

    # ------------------------------------------------------------ happy path

    def test_sound_draft_is_returned_unchanged_and_not_revised(self):
        provider = ScriptedProvider(assessment(), review("sound"))
        result = self.run_pipeline(provider)
        self.assertEqual(result.response, "The first draft.")
        self.assertFalse(result.revised)
        self.assertEqual(result.stages_run, ("draft", "assess", "critique"))

    def test_critiqued_draft_is_revised_and_verdict_describes_what_ships(self):
        provider = ScriptedProvider(
            assessment(),
            review("needs_revision", factual_errors=["got a fact wrong"],
                   most_important_fix="Correct the fact."),
            json.dumps({"answer": "A corrected answer.", "what_changed": "fixed the fact"}),
            review("sound"),
        )
        result = self.run_pipeline(provider)
        self.assertEqual(result.response, "A corrected answer.")
        self.assertTrue(result.revised)
        self.assertEqual(result.what_changed, "fixed the fact")
        self.assertEqual(result.review["verdict"], "sound")
        self.assertIn("revise", result.stages_run)

    def test_wrong_framing_also_triggers_revision(self):
        provider = ScriptedProvider(
            assessment(),
            review("wrong_framing", most_important_fix="The premise is false."),
            json.dumps({"answer": "Reframed answer.", "what_changed": "reframed"}),
            review("sound"),
        )
        result = self.run_pipeline(provider)
        self.assertTrue(result.revised)

    def test_revision_count_is_bounded(self):
        provider = ScriptedProvider(
            assessment(),
            review("needs_revision"),
            json.dumps({"answer": "v1", "what_changed": "one"}),
            review("needs_revision"),
            json.dumps({"answer": "v2", "what_changed": "two"}),
            review("needs_revision"),
        )
        result = self.run_pipeline(provider, max_revisions=1)
        self.assertEqual(result.response, "v1")
        self.assertEqual(result.stages_run.count("revise"), 1)

    def test_zero_revisions_never_calls_the_revision_stage(self):
        provider = ScriptedProvider(assessment(), review("needs_revision"))
        result = self.run_pipeline(provider, max_revisions=0)
        self.assertFalse(result.revised)
        self.assertEqual(result.response, "The first draft.")

    # ------------------------------------------------------------- dissent

    def test_false_premise_becomes_dissent(self):
        provider = ScriptedProvider(
            assessment(should_push_back=True, push_back="That premise is false.",
                       false_premise="the premise"),
            review("sound"),
        )
        result = self.run_pipeline(provider)
        self.assertEqual(result.dissent, "That premise is false.")

    def test_wrong_framing_without_pushback_still_records_dissent(self):
        provider = ScriptedProvider(
            assessment(),
            review("wrong_framing", most_important_fix="Reframe around the real problem."),
        )
        result = self.run_pipeline(provider, max_revisions=0)
        self.assertEqual(result.dissent, "Reframe around the real problem.")

    def test_sound_request_produces_no_dissent(self):
        provider = ScriptedProvider(assessment(), review("sound"))
        self.assertEqual(self.run_pipeline(provider).dissent, "")

    # ---------------------------------------------------------- confidence

    def test_confidence_is_discounted_for_what_the_critique_found(self):
        provider = ScriptedProvider(
            assessment(confidence_before=0.9),
            review("needs_revision", factual_errors=["wrong"], unsupported_claims=["unsourced"],
                   missed_the_question="missed the second half"),
            json.dumps({"answer": "Fixed.", "what_changed": "everything"}),
            review("sound"),
        )
        result = self.run_pipeline(provider)
        self.assertLess(result.confidence, 0.9)

    def test_confidence_stays_within_bounds_under_extreme_input(self):
        provider = ScriptedProvider(
            assessment(confidence_before=99),
            review("sound"),
        )
        self.assertLessEqual(self.run_pipeline(provider).confidence, 1.0)

    # ------------------------------------------------------------- degrade

    def test_unparseable_assessment_degrades_without_losing_the_answer(self):
        provider = ScriptedProvider("not json at all", review("sound"))
        result = self.run_pipeline(provider)
        self.assertEqual(result.response, "The first draft.")
        self.assertIn("Assessment stage failed", result.degraded)

    def test_unparseable_critique_keeps_the_draft(self):
        provider = ScriptedProvider(assessment(), "critique is not json")
        result = self.run_pipeline(provider)
        self.assertEqual(result.response, "The first draft.")
        self.assertIn("Critique stage failed", result.degraded)

    def test_failed_revision_falls_back_to_the_draft(self):
        provider = ScriptedProvider(
            assessment(),
            review("needs_revision"),
            "{broken json",
        )
        result = self.run_pipeline(provider)
        self.assertEqual(result.response, "The first draft.")
        self.assertFalse(result.revised)
        self.assertIn("Revision stage failed", result.degraded)

    def test_empty_revision_answer_falls_back_to_the_draft(self):
        provider = ScriptedProvider(
            assessment(),
            review("needs_revision"),
            json.dumps({"answer": "   ", "what_changed": "nothing"}),
        )
        result = self.run_pipeline(provider)
        self.assertEqual(result.response, "The first draft.")

    def test_assessment_can_be_skipped(self):
        provider = ScriptedProvider(review("sound"))
        result = self.run_pipeline(provider, skip_assessment=True)
        self.assertEqual(result.stages_run, ("draft", "critique"))

    def test_empty_draft_is_an_error_not_an_empty_answer(self):
        provider = ScriptedProvider()
        with self.assertRaises(ValueError):
            run_introspection(provider, "q", draft_fn=lambda t, c: "   ")

    def test_draft_fn_is_required(self):
        with self.assertRaises(ValueError):
            run_introspection(ScriptedProvider(), "q")

    # ------------------------------------------------------ JSON tolerance

    def test_fenced_and_prose_wrapped_json_is_accepted(self):
        fenced = "```json\n" + review("sound") + "\n```"
        provider = ScriptedProvider(assessment(), fenced)
        self.assertEqual(self.run_pipeline(provider).review["verdict"], "sound")

    def test_json_embedded_in_prose_is_extracted(self):
        provider = ScriptedProvider(assessment(), 'Here you go: ' + review("sound") + ' Hope that helps.')
        self.assertEqual(self.run_pipeline(provider).review["verdict"], "sound")

    def test_unknown_verdict_defaults_to_needs_revision(self):
        provider = ScriptedProvider(assessment(), review("brilliant"))
        self.assertEqual(self.run_pipeline(provider, max_revisions=0).review["verdict"], "needs_revision")

    def test_non_object_json_is_rejected_as_a_failed_stage(self):
        provider = ScriptedProvider(assessment(), "[1,2,3]")
        self.assertIn("Critique stage failed", self.run_pipeline(provider).degraded)

    # ------------------------------------------------------- serialisation

    def test_result_serialises_for_the_api(self):
        provider = ScriptedProvider(assessment(), review("sound"))
        payload = self.run_pipeline(provider).to_dict()
        self.assertEqual(set(payload) >= {
            "response", "draft", "revised", "what_changed", "assessment",
            "review", "confidence", "dissent", "assumptions", "unverified",
            "stages_run", "degraded",
        }, True)
        json.dumps(payload)

    # -------------------------------------------------- independent thinking

    def test_directive_requires_pushback_on_false_premises(self):
        directive = independent_thinker_directive()
        self.assertIn("false premise", directive)
        self.assertIn("Do not open with flattery", directive)

    def test_reflexive_agreement_is_stripped(self):
        self.assertEqual(strip_reflexive_agreement("Certainly! Here is the answer."), "Here is the answer.")
        self.assertEqual(strip_reflexive_agreement("You're absolutely right, it is."), "it is.")
        self.assertEqual(strip_reflexive_agreement("Great question! Let's see."), "Let's see.")

    def test_genuine_first_person_sentences_are_untouched(self):
        self.assertEqual(strip_reflexive_agreement("I was wrong about that."), "I was wrong about that.")


class CoordinatorIntrospectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.memory = LocalMemory(Path(self.temp.name) / "memory.sqlite3")

    def test_ask_without_introspection_makes_exactly_one_model_call(self):
        provider = ScriptedProvider("A direct answer.")
        coordinator = BabyMindCoordinator(provider=provider, memory=self.memory)
        result = coordinator.ask("BM-01", "Hello")
        self.assertEqual(result.response, "A direct answer.")
        self.assertIsNone(result.introspection)
        self.assertEqual(provider.calls, 1)

    def test_ask_with_introspection_records_the_self_review(self):
        provider = ScriptedProvider(
            "A draft.",
            assessment(should_push_back=True, push_back="The premise is wrong."),
            review("sound"),
        )
        coordinator = BabyMindCoordinator(provider=provider, memory=self.memory)
        result = coordinator.ask("BM-01", "A leading question?", introspect=True)
        self.assertIsNotNone(result.introspection)
        self.assertEqual(len(coordinator.selfmodel.recent_introspections()), 1)
        self.assertEqual(len(coordinator.selfmodel.recent_dissent()), 1)
        self.assertEqual(coordinator.selfmodel.recent_dissent()[0]["disagreement"], "The premise is wrong.")

    def test_every_prompt_carries_the_self_model_and_independence_rules(self):
        provider = ScriptedProvider("ok")
        coordinator = BabyMindCoordinator(provider=provider, memory=self.memory)
        coordinator.ask("BM-01", "Hello")
        system_prompt = provider.system_prompts[0]
        self.assertIn("SELF-MODEL", system_prompt)
        self.assertIn("INDEPENDENT REASONING", system_prompt)
        self.assertIn("BabyMind", system_prompt)

    def test_remembering_stores_the_final_revised_answer(self):
        provider = ScriptedProvider(
            "A wrong draft.",
            assessment(),
            review("needs_revision"),
            json.dumps({"answer": "The corrected final answer.", "what_changed": "fixed"}),
            review("sound"),
        )
        coordinator = BabyMindCoordinator(provider=provider, memory=self.memory)
        coordinator.ask("BM-01", "Question?", introspect=True, remember=True)
        self.assertEqual(self.memory.recent(limit=1)[0]["response"], "The corrected final answer.")

    def test_introspection_result_is_a_structured_dataclass(self):
        provider = ScriptedProvider("draft", assessment(), review("sound"))
        coordinator = BabyMindCoordinator(provider=provider, memory=self.memory)
        result = coordinator.ask("BM-01", "Question?", introspect=True)
        self.assertIsInstance(result.introspection, dict)
        self.assertIn("review", result.introspection)


if __name__ == "__main__":
    unittest.main()
