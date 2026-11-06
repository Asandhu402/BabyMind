"""Tests for the 50-role orchestrator."""
from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from babymind.agents import AGENTS
from babymind.orchestrator import (
    MissionError,
    MissionStore,
    Orchestrator,
    _agent_prompt,
    parse_model_json,
    phase_catalogue,
    role_catalogue,
)

BRIEF = "Build a small inventory application with a database and a report."


class FakeProvider:
    def __init__(self, fail_at: int | None = None) -> None:
        self.calls = 0
        self.fail_at = fail_at
        self.system_prompts = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        self.system_prompts.append(system_prompt)
        if self.fail_at is not None and self.calls == self.fail_at:
            raise RuntimeError("simulated provider failure")
        return "Contribution: concrete step with a file and a check."


class EmptyProvider:
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return "   "


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.store = MissionStore(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_every_role_is_recorded_in_a_full_mission(self) -> None:
        provider = FakeProvider()
        orchestrator = Orchestrator(provider, self.store, max_seconds=300)
        mission = orchestrator.run_now(BRIEF)
        self.assertEqual(mission["status"], "completed")
        self.assertEqual(mission["agents_recorded"], 50)
        self.assertEqual(mission["counts"].get("contributed"), 50)
        recorded = {run["agent_id"] for run in mission["runs"]}
        self.assertEqual(recorded, {agent.agent_id for agent in AGENTS})
        self.assertEqual(provider.calls, 50)
        self.assertEqual(len(provider.system_prompts), 50)
        self.assertTrue(all("COGNITIVE CORE" in prompt for prompt in provider.system_prompts))
        self.assertIn("returned non-empty text", mission["summary"])
        self.assertIn("unverified model text", mission["summary"])
        self.assertIn("does not prove the work was done", mission["summary"])

    def test_role_prompt_makes_text_only_boundaries_explicit(self) -> None:
        system, user = _agent_prompt(AGENTS[0], "Review a function.", "Earlier role output")
        self.assertIn("you have no tools", system)
        self.assertIn("never as completed actions", system)
        self.assertIn("unverified claims", system)
        self.assertIn("Earlier role output", user)

    def test_runs_follow_phase_order(self) -> None:
        mission = Orchestrator(FakeProvider(), self.store, max_seconds=300).run_now(BRIEF)
        phases = [run["phase"] for run in mission["runs"]]
        order = [phase["phase"] for phase in phase_catalogue()]
        self.assertEqual(phases, sorted(phases, key=order.index))

    def test_mission_routes_each_role_to_its_specialist_model(self) -> None:
        from babymind.agents import AGENTS
        class RoutedProvider:
            def __init__(self):
                self.agent_ids = []
            def complete(self, system_prompt, user_prompt):
                return "Fallback response."
            def complete_for(self, agent_id, system_prompt, user_prompt):
                self.agent_ids.append(agent_id)
                return "Specialist response."
        provider = RoutedProvider()
        mission = Orchestrator(provider, self.store, max_seconds=300).run_now(BRIEF)
        self.assertEqual(mission["status"], "completed")
        self.assertEqual(provider.agent_ids, [agent.agent_id for agent in AGENTS])

    def test_a_provider_failure_is_recorded_not_hidden(self) -> None:
        mission = Orchestrator(FakeProvider(fail_at=7), self.store, max_seconds=300).run_now(BRIEF)
        self.assertEqual(mission["status"], "partial")
        self.assertEqual(mission["counts"].get("error"), 1)
        self.assertEqual(mission["agents_recorded"], 50)
        errored = [run for run in mission["runs"] if run["status"] == "error"]
        self.assertIn("simulated provider failure", errored[0]["error"])

    def test_partial_mission_does_not_attempt_self_edit(self) -> None:
        orchestrator = Orchestrator(FakeProvider(fail_at=7), self.store, max_seconds=300)
        with patch.object(orchestrator, "_run_self_edit") as self_edit:
            mission = orchestrator.run_now(BRIEF, self_edit=True)
        self_edit.assert_not_called()
        self.assertEqual(mission["status"], "partial")
        self.assertEqual(mission["self_edit"]["status"], "skipped")
        self.assertEqual(mission["counts"].get("error"), 1)

    def test_budget_exhaustion_does_not_attempt_self_edit(self) -> None:
        orchestrator = Orchestrator(FakeProvider(), self.store, max_seconds=300)
        orchestrator.on_update = lambda _id, _run: setattr(orchestrator, "max_seconds", 0)
        with patch.object(orchestrator, "_run_self_edit") as self_edit:
            mission = orchestrator.run_now(BRIEF, self_edit=True)
        self_edit.assert_not_called()
        self.assertEqual(mission["status"], "partial")
        self.assertGreater(mission["counts"].get("deferred", 0), 0)
        self.assertEqual(mission["self_edit"]["status"], "skipped")

    def test_cancellation_during_final_role_does_not_attempt_self_edit(self) -> None:
        orchestrator = Orchestrator(FakeProvider(), self.store, max_seconds=300)
        def cancel_at_final(mission_id, run):
            if run.agent_id == AGENTS[-1].agent_id:
                self.store.request_cancel(mission_id)
        orchestrator.on_update = cancel_at_final
        with patch.object(orchestrator, "_run_self_edit") as self_edit:
            mission = orchestrator.run_now(BRIEF, self_edit=True)
        self_edit.assert_not_called()
        self.assertEqual(mission["status"], "cancelled")
        self.assertEqual(mission["self_edit"]["status"], "skipped")
        self.assertEqual(mission["agents_recorded"], 50)

    def test_empty_contributions_count_as_errors(self) -> None:
        mission = Orchestrator(EmptyProvider(), self.store, max_seconds=300).run_now(BRIEF)
        self.assertEqual(mission["status"], "failed")
        self.assertEqual(mission["counts"].get("error"), 50)

    def test_cancellation_still_records_all_roles(self) -> None:
        mission_id = self.store.create(BRIEF, "batched")
        self.store.request_cancel(mission_id)
        orchestrator = Orchestrator(FakeProvider(), self.store, max_seconds=300)
        mission = orchestrator.run_now(BRIEF, mission_id=mission_id)
        self.assertEqual(mission["status"], "cancelled")
        self.assertEqual(mission["agents_recorded"], 50)
        self.assertEqual(mission["counts"].get("deferred"), 50)

    def test_brief_is_validated(self) -> None:
        with self.assertRaises(MissionError):
            Orchestrator(FakeProvider(), self.store).start("hi")

    def test_agent_stats_cover_every_role(self) -> None:
        Orchestrator(FakeProvider(), self.store, max_seconds=300).run_now(BRIEF)
        stats = self.store.agent_stats()
        self.assertEqual(len(stats), 50)
        self.assertTrue(all(item["runs"] == 1 for item in stats))
        self.assertTrue(all(item["capabilities"] for item in stats))

    def test_role_catalogue_matches_the_registry(self) -> None:
        roles = role_catalogue()
        self.assertEqual(len(roles), 50)
        self.assertEqual({role["agent_id"] for role in roles}, {agent.agent_id for agent in AGENTS})
        self.assertEqual(roles[0]["name"], "Chief Architect")
        self.assertEqual(roles[-1]["name"], "Final Acceptance and Release Manager")

    def test_start_returns_immediately_and_completes(self) -> None:
        orchestrator = Orchestrator(FakeProvider(), self.store, max_seconds=300)
        mission_id = orchestrator.start(BRIEF)
        orchestrator._threads[mission_id].join(timeout=30)
        mission = self.store.get(mission_id)
        self.assertEqual(mission["status"], "completed")
        self.assertEqual(mission["agents_recorded"], 50)


class SelfEditProvider:
    """Role calls return prose; the self-edit call returns a JSON patch."""

    def __init__(self, patch: dict | str | None) -> None:
        self.patch = patch
        self.self_edit_calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if "closing a mission" in system_prompt:
            self.self_edit_calls += 1
            return self.patch if isinstance(self.patch, str) else json.dumps(self.patch or {})
        return "Contribution: concrete step."


class SequencedSelfEditProvider:
    """Returns a different patch on every self-edit call, in order."""

    def __init__(self, patches: list[dict | str]) -> None:
        self.patches = list(patches)
        self.self_edit_calls = 0
        self.prompts: list[str] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if "closing a mission" in system_prompt:
            index = min(self.self_edit_calls, len(self.patches) - 1)
            self.self_edit_calls += 1
            self.prompts.append(user_prompt)
            patch = self.patches[index]
            return patch if isinstance(patch, str) else json.dumps(patch)
        return "Contribution: concrete step."


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


class SelfEditLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        _make_checkout(self.root)
        self.env = patch.dict(os.environ, {
            "BABYMIND_DEV_ROOT": str(self.root),
            "BABYMIND_SELF_DEVELOPMENT_ENABLED": "true",
            "BABYMIND_SANDBOX": "off",  # trusted disposable unit-test fixture
        })
        self.env.start()
        self.store = MissionStore(str(self.root / ".missions"))

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def test_accepted_patch_is_applied_and_verified(self) -> None:
        provider = SelfEditProvider({
            "reason": "raise the value",
            "edits": [{"path": "src/babymind/mod.py", "content": "VALUE = 2\n"}],
        })
        mission = Orchestrator(provider, self.store, max_seconds=120).run_now(
            "Improve the module value.", self_edit=True
        )
        self.assertEqual(mission["status"], "completed")
        self.assertEqual(mission["self_edit"]["status"], "applied", mission["self_edit"])
        self.assertIn("src/babymind/mod.py", mission["self_edit"]["files"])
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 2\n")
        self.assertEqual(provider.self_edit_calls, 1)

    def test_failing_patch_is_rolled_back_by_the_engine(self) -> None:
        provider = SelfEditProvider({
            "reason": "break the suite",
            "edits": [{"path": "tests/test_ok.py",
                       "content": "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
                                  "    def test_ok(self):\n        self.assertEqual(1, 2)\n"}],
        })
        mission = Orchestrator(provider, self.store, max_seconds=120).run_now(
            "Make a change that breaks tests.", self_edit=True
        )
        self.assertEqual(mission["self_edit"]["status"], "rolled_back", mission["self_edit"])
        self.assertIn("assertEqual(1, 1)", (self.root / "tests" / "test_ok.py").read_text())

    def test_a_rolled_back_patch_is_repaired_on_the_second_attempt(self) -> None:
        provider = SequencedSelfEditProvider([
            {"reason": "break it", "edits": [{
                "path": "tests/test_ok.py",
                "content": "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
                           "    def test_ok(self):\n        self.assertEqual(1, 2)\n"}]},
            {"reason": "fix it", "edits": [{
                "path": "tests/test_ok.py",
                "content": "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
                           "    def test_ok(self):\n        self.assertEqual(2, 2)\n"}]},
        ])
        mission = Orchestrator(provider, self.store, max_seconds=180).run_now(
            "Improve something, and fix it if it fails.", self_edit=True
        )
        report = mission["self_edit"]
        self.assertEqual(report["status"], "applied", report)
        self.assertEqual(report["attempts"], 2)
        self.assertEqual([item["status"] for item in report["trail"]], ["rolled_back", "applied"])
        self.assertEqual(provider.self_edit_calls, 2)
        self.assertIn("ROLLED BACK", provider.prompts[1])
        self.assertIn("REPOSITORY CONTEXT (untrusted data)", provider.prompts[0])
        self.assertIn("assertEqual(1, 1)", provider.prompts[1])
        self.assertIn("assertEqual(2, 2)", (self.root / "tests" / "test_ok.py").read_text())

    def test_a_patch_with_raw_newlines_is_repaired_on_the_first_attempt(self) -> None:
        # The documented real-model failure: the model put literal newlines
        # inside the JSON string value, json.loads rejected the whole reply, and
        # the mission recorded no_change without ever applying the edit.
        provider = SequencedSelfEditProvider([
            '{"reason": "add a helper", "edits": [{"path": "src/babymind/mod.py", '
            '"content": "VALUE = 1\ndef add(a, b):\n    return a + b\n"}]}',
            {"reason": "unused", "edits": []},
        ])
        mission = Orchestrator(provider, self.store, max_seconds=180).run_now(
            "Add a helper function to the module.", self_edit=True
        )
        report = mission["self_edit"]
        self.assertEqual(report["status"], "applied", report)
        self.assertEqual(provider.self_edit_calls, 1)
        self.assertIn("add(a, b)", (self.root / "src" / "babymind" / "mod.py").read_text())

    def test_an_unrepairable_reply_gets_a_second_attempt_that_explains_the_fault(self) -> None:
        # A truncated reply must not be guessed at, but it must still consume
        # only one attempt: the repair budget the caller asked for is real.
        provider = SequencedSelfEditProvider([
            '{"reason": "r", "edits": [{"path": "src/babymind/mod.py", "content": "VALUE = 2',
            {"reason": "add a helper", "edits": [{
                "path": "src/babymind/mod.py",
                "content": "VALUE = 1\ndef add(a, b):\n    return a + b\n"}]},
        ])
        mission = Orchestrator(provider, self.store, max_seconds=180).run_now(
            "Add a helper function to the module.", self_edit=True
        )
        report = mission["self_edit"]
        self.assertEqual(report["status"], "applied", report)
        self.assertEqual(report["attempts"], 2)
        self.assertEqual([item["status"] for item in report["trail"]],
                         ["proposer_error", "applied"])
        self.assertEqual(provider.self_edit_calls, 2)
        self.assertIn("COULD NOT BE USED", provider.prompts[1])
        self.assertIn("cut off", provider.prompts[1])
        self.assertIn("add(a, b)", (self.root / "src" / "babymind" / "mod.py").read_text())

    def test_two_unparseable_patches_are_reported_without_touching_the_tree(self) -> None:
        provider = SequencedSelfEditProvider(['{"reason": "r", "edits": [{"path": "x.py"'] * 2)
        mission = Orchestrator(provider, self.store, max_seconds=180).run_now(
            "Add a helper function to the module.", self_edit=True
        )
        report = mission["self_edit"]
        self.assertEqual(report["status"], "no_change", report)
        self.assertEqual(provider.self_edit_calls, 2)
        self.assertIn("COULD NOT BE USED", provider.prompts[1])
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")

    def test_two_failed_attempts_leave_the_tree_untouched(self) -> None:
        bad = {"reason": "still broken", "edits": [{
            "path": "tests/test_ok.py",
            "content": "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
                       "    def test_ok(self):\n        self.assertEqual(1, 3)\n"}]}
        provider = SequencedSelfEditProvider([bad, bad, bad])
        mission = Orchestrator(provider, self.store, max_seconds=180).run_now(
            "Try twice and give up.", self_edit=True
        )
        report = mission["self_edit"]
        self.assertEqual(report["status"], "rolled_back", report)
        self.assertEqual(report["attempts"], 2)
        self.assertEqual(provider.self_edit_calls, 2)
        self.assertIn("assertEqual(1, 1)", (self.root / "tests" / "test_ok.py").read_text())
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")

    def test_a_first_attempt_success_is_not_retried(self) -> None:
        provider = SequencedSelfEditProvider([
            {"reason": "good", "edits": [{"path": "src/babymind/mod.py", "content": "VALUE = 5\n"}]},
        ])
        mission = Orchestrator(provider, self.store, max_seconds=180).run_now(
            "Improve the module.", self_edit=True
        )
        self.assertEqual(mission["self_edit"]["status"], "applied")
        self.assertEqual(mission["self_edit"]["attempts"], 1)
        self.assertEqual(provider.self_edit_calls, 1)

    def test_garbage_model_output_changes_nothing(self) -> None:
        provider = SelfEditProvider("I cannot produce JSON today.")
        mission = Orchestrator(provider, self.store, max_seconds=120).run_now(
            "Improve something.", self_edit=True
        )
        self.assertEqual(mission["self_edit"]["status"], "no_change")
        self.assertEqual((self.root / "src" / "babymind" / "mod.py").read_text(), "VALUE = 1\n")

    def test_no_edits_is_recorded_as_no_change(self) -> None:
        provider = SelfEditProvider({"reason": "nothing safe to change", "edits": []})
        mission = Orchestrator(provider, self.store, max_seconds=120).run_now(
            "Improve something.", self_edit=True
        )
        self.assertEqual(mission["self_edit"]["status"], "no_change")
        self.assertIn("nothing safe", mission["self_edit"]["detail"])

    def test_protected_paths_are_rejected(self) -> None:
        provider = SelfEditProvider({"reason": "escape", "edits": [{"path": "../evil.py", "content": "x = 1\n"}]})
        mission = Orchestrator(provider, self.store, max_seconds=120).run_now(
            "Improve something.", self_edit=True
        )
        self.assertEqual(mission["self_edit"]["status"], "rejected")

    def test_disabled_engine_skips_the_loop(self) -> None:
        provider = SelfEditProvider({"reason": "x", "edits": []})
        with patch.dict(os.environ, {"BABYMIND_SELF_DEVELOPMENT_ENABLED": "false"}):
            mission = Orchestrator(provider, self.store, max_seconds=120).run_now(
                "Improve something.", self_edit=True
            )
        self.assertEqual(mission["self_edit"]["status"], "skipped")
        self.assertEqual(provider.self_edit_calls, 0)

    def test_loop_does_not_run_without_the_flag(self) -> None:
        provider = SelfEditProvider({"reason": "x", "edits": []})
        mission = Orchestrator(provider, self.store, max_seconds=120).run_now("Improve something.")
        self.assertIsNone(mission["self_edit"])
        self.assertEqual(provider.self_edit_calls, 0)


if __name__ == "__main__":
    unittest.main()


class GraphMissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.store = MissionStore(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_parallel_phase_receives_only_prior_phases(self) -> None:
        import re
        from babymind.agents import PHASES
        class RecordingProvider:
            def __init__(self):
                self.prompts = {}
            def complete(self, system, user):
                agent_id = re.search(r'Specialist identity: .*?\((BM-\d+)\)', system).group(1)
                self.prompts[agent_id] = user
                return 'Contribution from ' + agent_id
        provider = RecordingProvider()
        mission = Orchestrator(provider, self.store, max_seconds=300).run_now(BRIEF, mode='graph')
        self.assertEqual(mission['status'], 'completed')
        for agent in AGENTS:
            for other in AGENTS:
                if other.phase == agent.phase:
                    self.assertNotIn('Contribution from ' + other.agent_id, provider.prompts[agent.agent_id])
            if PHASES.index(agent.phase):
                self.assertIn('Contribution from', provider.prompts[agent.agent_id])

    def test_graph_mode_records_all_50_roles(self) -> None:
        provider = FakeProvider()
        orchestrator = Orchestrator(provider, self.store, max_seconds=300)
        mission = orchestrator.run_now(BRIEF, mode="graph")
        self.assertEqual(mission["status"], "completed")
        self.assertEqual(mission["agents_recorded"], 50)
        self.assertIn("task-graph mode", mission["summary"])
        self.assertEqual(provider.calls, 50)


class GraphSelfEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.store = MissionStore(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_role_failure_defers_dependents_and_prevents_self_edit(self) -> None:
        class FailingProvider:
            def complete(self, system, user):
                if 'BM-02' in system:
                    raise RuntimeError('model failed')
                return 'A contribution.'
        orchestrator = Orchestrator(FailingProvider(), self.store, max_seconds=300)
        with patch.object(Orchestrator, '_run_self_edit') as edit:
            mission = orchestrator.run_now(BRIEF, mode='graph', self_edit=True)
        edit.assert_not_called()
        self.assertEqual(mission['agents_recorded'], 50)
        self.assertEqual(mission['status'], 'failed')
        self.assertEqual(mission['counts'].get('error'), 1)
        self.assertEqual(mission['counts'].get('deferred'), 49)
        self.assertEqual(mission['self_edit']['status'], 'skipped')

    def test_graph_deadline_stops_scheduling_and_skips_self_edit(self) -> None:
        class DeadlineProvider:
            def complete(self, system, user):
                orchestrator.max_seconds = 0
                return 'A contribution.'
        orchestrator = Orchestrator(DeadlineProvider(), self.store, max_seconds=300)
        with patch.object(Orchestrator, '_run_self_edit') as edit:
            mission = orchestrator.run_now(BRIEF, mode='graph', self_edit=True)
        edit.assert_not_called()
        self.assertEqual(mission['agents_recorded'], 50)
        self.assertEqual(mission['status'], 'partial')
        self.assertIn('Time limit reached', mission['summary'])
        self.assertEqual(mission['self_edit']['status'], 'skipped')

    def test_graph_mode_runs_self_edit_when_completed(self) -> None:
        provider = FakeProvider()
        orchestrator = Orchestrator(provider, self.store, max_seconds=300)
        with patch.object(Orchestrator, "_run_self_edit",
                          return_value={"status": "applied", "detail": "ok"}) as se:
            mission = orchestrator.run_now(BRIEF, mode="graph", self_edit=True)
        self.assertEqual(mission["status"], "completed")
        se.assert_called_once()
        self.assertIn("Self-edit: applied", mission["summary"])

    def test_graph_mode_skips_self_edit_when_cancelled(self) -> None:
        provider = FakeProvider()
        orchestrator = Orchestrator(provider, self.store, max_seconds=300)
        mid = self.store.create(BRIEF, "graph")
        self.store.request_cancel(mid)
        with patch.object(Orchestrator, "_run_self_edit") as se:
            orchestrator._run_graph(mid, BRIEF, self_edit=True)
        se.assert_not_called()
        self.assertEqual(self.store.get(mid)["status"], "cancelled")


class GraphCancellationTests(unittest.TestCase):
    def test_mission_cancel_flag_stops_graph(self) -> None:
        import threading
        store = MissionStore(TemporaryDirectory().name)
        provider = FakeProvider()
        orchestrator = Orchestrator(provider, store, max_seconds=300)

        class SlowProvider:
            def complete(self, s, u):
                time.sleep(0.05)
                return "text"
        orchestrator.provider = SlowProvider()
        mid = store.create(BRIEF, "graph")
        store.request_cancel(mid)  # cancel before the graph starts
        orchestrator._run_graph(mid, BRIEF)
        mission = store.get(mid)
        self.assertEqual(mission["status"], "cancelled")


class ParseModelJsonTests(unittest.TestCase):
    """A self-edit proposal is free model text, so parsing it must not be brittle.

    These cover the shapes the pinned model actually produced: raw newlines
    inside a string value, a brace in the surrounding prose, a Markdown fence,
    and a reply cut off mid-object.
    """

    def test_raw_newlines_inside_a_string_value_are_repaired(self) -> None:
        raw = ('{"reason": "add a helper", "edits": [{"path": "src/babymind/mod.py", '
               '"content": "VALUE = 1\ndef add(a, b):\n    return a + b\n"}]}')
        with self.assertRaises(json.JSONDecodeError):
            json.loads(raw)  # the failure this exists to survive
        parsed = parse_model_json(raw)
        self.assertEqual(parsed["edits"][0]["content"], "VALUE = 1\ndef add(a, b):\n    return a + b\n")

    def test_prose_after_the_object_cannot_extend_it(self) -> None:
        raw = 'Here is the patch:\n{"reason": "r", "edits": []}\nTell me if you want {more}.'
        with self.assertRaises(json.JSONDecodeError):
            json.loads(raw[raw.find("{"):raw.rfind("}") + 1])  # the old slice
        self.assertEqual(parse_model_json(raw), {"reason": "r", "edits": []})

    def test_a_stray_brace_in_prose_does_not_hide_the_real_object(self) -> None:
        raw = 'Use a {dict} here.\n{"reason": "r", "edits": []}'
        self.assertEqual(parse_model_json(raw), {"reason": "r", "edits": []})

    def test_a_code_fence_is_stripped(self) -> None:
        raw = '```json\n{"reason": "r", "edits": []}\n```'
        self.assertEqual(parse_model_json(raw), {"reason": "r", "edits": []})

    def test_already_valid_json_survives_the_repair_unchanged(self) -> None:
        payload = {"reason": 'a "quoted" reason with an escaped \n newline', "edits": []}
        self.assertEqual(parse_model_json(json.dumps(payload)), payload)

    def test_a_truncated_object_is_reported_and_never_completed(self) -> None:
        raw = '{"reason": "r", "edits": [{"path": "src/babymind/mod.py", "content": "VALUE = 1'
        with self.assertRaises(ValueError) as caught:
            parse_model_json(raw)
        self.assertIn("cut off", str(caught.exception))

    def test_a_truncated_outer_object_is_not_satisfied_by_a_complete_inner_one(self) -> None:
        raw = '{"reason": "r", "edits": [{"path": "a.py", "content": "VALUE = 1"}]'
        with self.assertRaises(ValueError) as caught:
            parse_model_json(raw)
        self.assertIn("cut off", str(caught.exception))

    def test_invalid_json_that_repair_cannot_fix_names_the_reason(self) -> None:
        with self.assertRaises(ValueError) as caught:
            parse_model_json('{"reason": "r", "edits": [}')
        self.assertIn("invalid JSON", str(caught.exception))

    def test_a_reply_with_no_object_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            parse_model_json("I cannot make that change safely.")
        self.assertIn("no JSON object", str(caught.exception))
