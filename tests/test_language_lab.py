"""Tests for the web-researched, execution-verified language development cycle.

These tests exercise the machinery: specification validation, the independent
rounding oracle, sandboxed execution, held-out probing, conformance decisions,
research plumbing and the durable record. The model is scripted throughout, so
nothing here measures whether a real model would design a good language.

Tests that need a real OS sandbox skip when none is available, matching the
convention in test_builder.py and test_sandbox.py.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from babymind import language_lab
from babymind.independence import Independence

# A genuine, minimal implementation of the test language: it parses
# "dika NUMBER UNIT", rounds half-up to two places with decimal, and fails
# cleanly on anything else. Used to prove the sandboxed path really executes.
REAL_INTERPRETER = '''\
import sys
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

PLACES = 2


def fail(message):
    print("numa: " + message, file=sys.stderr)
    raise SystemExit(1)


try:
    source = open(sys.argv[1], encoding="utf-8").read()
except (OSError, IndexError):
    fail("cannot read program file")

for raw in source.splitlines():
    line = raw.strip()
    if not line:
        continue
    parts = line.split()
    if len(parts) != 3 or parts[0] != "dika":
        fail("bad statement: " + line)
    try:
        value = Decimal(parts[1])
    except InvalidOperation:
        fail("bad number: " + parts[1])
    if not value.is_finite():
        fail("bad number: " + parts[1])
    rounded = value.quantize(Decimal(1).scaleb(-PLACES), rounding=ROUND_HALF_UP)
    print(format(rounded, "f") + " " + parts[2])
'''

# Prints only the answers it was shown. Nothing is computed, so any number the
# harness invents must come out wrong.
HARDCODED_INTERPRETER = '''\
import sys
ANSWERS = {"12.345": "12.35", "7.005": "7.01"}
for raw in open(sys.argv[1], encoding="utf-8").read().splitlines():
    parts = raw.split()
    if len(parts) != 3 or parts[0] != "dika":
        print("numa: bad statement", file=sys.stderr)
        raise SystemExit(1)
    if parts[1] in ANSWERS:
        print(ANSWERS[parts[1]] + " " + parts[2])
    else:
        # The literal case never stated a number, so echo unrounded. This
        # reproduces every declared expectation without implementing rounding.
        print(parts[1] + " " + parts[2])
'''


def make_spec(content: str = REAL_INTERPRETER, **overrides) -> dict:
    spec = {
        "name": "Numa",
        "purpose": "Print measured quantities rounded to two places.",
        "keywords": [{"token": "dika", "meaning": "print a rounded quantity"}],
        "syntax_rules": [
            "A program is one or more statements.",
            "Each statement is: dika NUMBER UNIT.",
        ],
        "semantics": {"number_places": 2, "rounding": "half_up"},
        "entry": "interpreter.py",
        "rejects_invalid_programs": True,
        "conformance": [
            {"name": "greeting", "kind": "literal", "program": "dika 3.5 km",
             "expect_stdout": "3.50 km"},
            {"name": "r1", "kind": "rounding", "program": "dika 12.345 km",
             "input_number": "12.345", "expect_number": "12.35"},
            {"name": "r2", "kind": "rounding", "program": "dika 7.005 kg",
             "input_number": "7.005", "expect_number": "7.01"},
        ],
        "files": [{"path": "interpreter.py", "content": content}],
    }
    spec.update(overrides)
    return spec


class ScriptedProvider:
    """Returns scripted responses in order and records every prompt."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise AssertionError("provider called more times than scripted")
        item = self._responses.pop(0)
        return item if isinstance(item, str) else json.dumps(item)


def _design_reply(**overrides) -> str:
    return json.dumps(make_spec(**overrides))


class LabTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"
        self.root = Path(self.temp.name) / "lab"
        self.root.mkdir()
        self.env = mock.patch.dict(
            os.environ,
            {
                "BABYMIND_LANGUAGE_LAB_ENABLED": "true",
                "BABYMIND_LANGUAGE_LAB_ROOT": str(self.root),
                "BABYMIND_OFFLINE": "0",
            },
        )
        self.env.start()
        self.independence = Independence(home=self.home)

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def lab(self):
        return self.independence.languages


# ------------------------------------------------------------------ the oracle


class OracleTests(unittest.TestCase):
    def test_rounding_modes_are_computed_independently(self) -> None:
        cases = {
            ("2.345", 2, "half_up"): "2.35",
            ("2.345", 2, "half_even"): "2.34",
            ("2.355", 2, "half_even"): "2.36",
            ("2.349", 2, "up"): "2.35",
            ("2.349", 2, "down"): "2.34",
            ("-1.5", 0, "floor"): "-2",
            ("-1.5", 0, "ceiling"): "-1",
            ("7", 2, "half_up"): "7.00",
            ("0.5", 0, "half_up"): "1",
        }
        for (number, places, mode), expected in cases.items():
            with self.subTest(number=number, places=places, mode=mode):
                self.assertEqual(language_lab.oracle_round(number, places, mode), expected)

    def test_oracle_rejects_inputs_it_cannot_recompute(self) -> None:
        for bad in (("abc", 2, "half_up"), ("1.5", 2, "nearest"), ("1.5", True, "half_up"),
                    ("1.5", 12, "half_up"), ("1.5", 2, "")):
            with self.subTest(bad=bad), self.assertRaises(language_lab.LabError):
                language_lab.oracle_round(*bad)


# --------------------------------------------------------- specification rules


class SpecificationValidationTests(unittest.TestCase):
    def validate(self, spec: dict) -> dict:
        return language_lab._normalise_spec(spec)

    def test_a_well_formed_specification_is_normalised(self) -> None:
        spec = self.validate(make_spec())
        self.assertEqual(spec["slug"], "numa")
        self.assertEqual(spec["entry"], "interpreter.py")
        self.assertEqual(len(spec["conformance"]), 3)
        self.assertTrue(spec["rejects_invalid_programs"])

    def test_declared_number_must_match_the_declared_rule(self) -> None:
        # The model claims 12.34 for half_up, which is wrong. Validation does not
        # catch this (it needs the oracle), but the conformance stage must.
        spec = make_spec()
        spec["conformance"][1]["expect_number"] = "12.34"
        normalised = self.validate(spec)
        self.assertEqual(normalised["conformance"][1]["expect_number"], "12.34")
        result = language_lab.evaluate_conformance(
            normalised, Path(tempfile.mkdtemp())
        )
        self.assertFalse(result["passed"])
        self.assertTrue(any("declared 12.34" in failure for failure in result["failures"]))

    def test_two_rounding_cases_are_required(self) -> None:
        spec = make_spec()
        spec["conformance"] = [spec["conformance"][0], spec["conformance"][1]]
        with self.assertRaises(language_lab.LabError):
            self.validate(spec)

    def test_a_literal_case_is_required(self) -> None:
        spec = make_spec()
        spec["conformance"] = spec["conformance"][1:]
        with self.assertRaises(language_lab.LabError):
            self.validate(spec)

    def test_rounding_cases_cannot_reuse_one_input(self) -> None:
        spec = make_spec()
        spec["conformance"][2]["input_number"] = "12.345"
        spec["conformance"][2]["expect_number"] = "12.35"
        with self.assertRaises(language_lab.LabError) as caught:
            self.validate(spec)
        self.assertIn("two different input numbers", str(caught.exception))

    def test_duplicate_keywords_are_rejected(self) -> None:
        spec = make_spec()
        spec["keywords"] = [{"token": "dika", "meaning": "a"}, {"token": "DIKA", "meaning": "b"}]
        with self.assertRaises(language_lab.LabError):
            self.validate(spec)

    def test_path_traversal_and_hidden_paths_are_refused(self) -> None:
        for path in ("../escape.py", "/etc/passwd", ".hidden.py", "a/../../b.py",
                     "state/interpreter.py", "interpreter.exe", "key.py"):
            with self.subTest(path=path):
                spec = make_spec()
                spec["files"] = [{"path": path, "content": "print(1)"}]
                spec["entry"] = path if path.endswith(".py") else "interpreter.py"
                with self.assertRaises(language_lab.LabError):
                    self.validate(spec)

    def test_entry_must_be_one_of_the_generated_files(self) -> None:
        spec = make_spec(entry="main.py")
        with self.assertRaises(language_lab.LabError):
            self.validate(spec)

    def test_oversized_specification_is_refused(self) -> None:
        spec = make_spec()
        spec["purpose"] = "x" * 30_000
        with self.assertRaises(language_lab.LabError):
            self.validate(spec)

    def test_digest_changes_when_any_behaviour_changes(self) -> None:
        base = language_lab.spec_digest(language_lab._normalise_spec(make_spec()))
        changed = make_spec()
        changed["semantics"] = {"number_places": 2, "rounding": "half_even"}
        changed["conformance"][1]["expect_number"] = "12.34"
        changed["conformance"][2]["expect_number"] = "7.00"
        self.assertNotEqual(
            base, language_lab.spec_digest(language_lab._normalise_spec(changed))
        )


# --------------------------------------------------------------- held-out math


class HeldOutNumberTests(unittest.TestCase):
    def test_derived_numbers_are_unseen_and_round_differently(self) -> None:
        original = "12.345"
        base = language_lab.oracle_round(original, 2, "half_up")
        derived = language_lab._held_out_numbers(original, 2)
        self.assertTrue(derived)
        self.assertNotIn(original, derived)
        for candidate in derived:
            self.assertNotEqual(language_lab.oracle_round(candidate, 2, "half_up"), base)

    def test_unparseable_input_yields_no_candidates(self) -> None:
        self.assertEqual(language_lab._held_out_numbers("abc", 2), [])


# ------------------------------------------------------------ cycle behaviour


class CycleRefusalTests(LabTestBase):
    def test_the_lab_is_off_by_default(self) -> None:
        with mock.patch.dict(os.environ, {"BABYMIND_LANGUAGE_LAB_ENABLED": ""}):
            self.assertFalse(language_lab.lab_enabled())
            status = language_lab.lab_status()
            self.assertFalse(status["enabled"])
            self.assertFalse(status["runs_generated_interpreters"])

    def test_a_disabled_lab_refuses_to_run(self) -> None:
        with mock.patch.dict(os.environ, {"BABYMIND_LANGUAGE_LAB_ENABLED": "false"}):
            with self.assertRaises(language_lab.LabError):
                self.lab().run(ScriptedProvider([]), allow_research=False)

    def test_an_unconfigured_root_is_reported_not_invented(self) -> None:
        with mock.patch.dict(os.environ, {"BABYMIND_LANGUAGE_LAB_ROOT": "",
                                          "BABYMIND_WORKSPACE_ROOT": ""}):
            status = language_lab.lab_status()
            self.assertIsNone(status["root"])
            self.assertFalse(status["ready"])
            self.assertIn("BABYMIND_LANGUAGE_LAB_ROOT", status["problem"])

    def test_the_cycle_fails_closed_without_a_sandbox(self) -> None:
        unavailable = {"available": False, "backend": "none", "detail": "none"}
        with mock.patch.object(language_lab, "_sandbox", return_value=unavailable):
            with self.assertRaises(language_lab.LabError) as caught:
                self.lab().run(ScriptedProvider([_design_reply()]), allow_research=False)
        self.assertIn("fails closed", str(caught.exception))
        self.assertEqual(self.languages_written(), [])

    def test_an_invalid_design_is_rejected_and_nothing_is_written(self) -> None:
        broken = json.dumps({"name": "Broken"})
        provider = ScriptedProvider([broken])
        report = self.lab().run(provider, allow_research=False)
        self.assertEqual(report["status"], "rejected")
        self.assertEqual(report["stage"], "validate")
        self.assertIn("purpose", report["reason"])
        self.assertEqual(self.languages_written(), [])

    def test_a_second_attempt_is_given_the_validation_error(self) -> None:
        broken = json.dumps({"name": "Broken"})
        provider = ScriptedProvider([broken, _design_reply()])
        with mock.patch.object(language_lab, "evaluate_conformance",
                               return_value={"passed": True, "checks": [], "failures": [],
                                             "summary": "0/0"}):
            report = self.lab().run(provider, allow_research=False, max_attempts=2)
        self.assertEqual(report["status"], "verified")
        self.assertIn("REJECTED", provider.calls[1][1])
        self.assertIn("purpose", provider.calls[1][1])

    def languages_written(self) -> list[str]:
        folder = self.root / "languages"
        return sorted(item.name for item in folder.iterdir()) if folder.is_dir() else []


class ResearchTests(LabTestBase):
    def test_research_is_off_unless_authorised(self) -> None:
        with mock.patch("babymind.research.search_web") as search:
            provider = ScriptedProvider([_design_reply()])
            with mock.patch.object(language_lab, "evaluate_conformance",
                                   return_value={"passed": True, "checks": [],
                                                 "failures": [], "summary": "0/0"}):
                report = self.lab().run(provider, allow_research=False)
        search.assert_not_called()
        self.assertFalse(report["research"]["performed"])
        self.assertIn("not authorised", report["research"]["reason"])

    def test_read_pages_reach_the_design_prompt_but_snippets_do_not(self) -> None:
        def fetch(url):
            return {"url": url, "title": "Language design notes",
                    "text": "READ PAGE CONTENT about grammars", "truncated": 0}

        # The first provider call is the search-query plan; the design follows.
        plan = json.dumps({"queries": ["language grammar design"]})
        with mock.patch("babymind.research.search_web",
                        return_value=[{"url": "https://example.com/a",
                                       "snippet": "SNIPPET ONLY"}]), \
             mock.patch("babymind.research.fetch_page", side_effect=fetch):
            provider = ScriptedProvider([plan, _design_reply()])
            with mock.patch.object(language_lab, "evaluate_conformance",
                                   return_value={"passed": True, "checks": [],
                                                 "failures": [], "summary": "0/0"}):
                report = self.lab().run(provider, allow_research=True)

        design_prompt = provider.calls[-1][1]
        self.assertIn("READ PAGE CONTENT", design_prompt)
        self.assertNotIn("SNIPPET ONLY", design_prompt)
        self.assertTrue(report["research"]["performed"])
        self.assertEqual(report["research"]["sources"][0]["url"], "https://example.com/a")

    def test_failed_fetches_are_reported_and_do_not_abort_the_cycle(self) -> None:
        with mock.patch("babymind.research.search_web",
                        return_value=[{"url": "https://example.com/a", "snippet": "s"}]), \
             mock.patch("babymind.research.fetch_page",
                        side_effect=RuntimeError("unreadable")):
            provider = ScriptedProvider([json.dumps({"queries": ["x"]}), _design_reply()])
            with mock.patch.object(language_lab, "evaluate_conformance",
                                   return_value={"passed": True, "checks": [],
                                                 "failures": [], "summary": "0/0"}):
                report = self.lab().run(provider, allow_research=True)
        self.assertEqual(report["status"], "verified")
        self.assertTrue(any("unreadable" in failure for failure in report["research"]["failures"]))

    def test_offline_mode_refuses_research(self) -> None:
        with mock.patch.dict(os.environ, {"BABYMIND_OFFLINE": "1"}), \
             mock.patch("babymind.research.search_web") as search:
            provider = ScriptedProvider([_design_reply()])
            with mock.patch.object(language_lab, "evaluate_conformance",
                                   return_value={"passed": True, "checks": [],
                                                 "failures": [], "summary": "0/0"}):
                report = self.lab().run(provider, allow_research=True)
        search.assert_not_called()
        self.assertFalse(report["research"]["performed"])
        self.assertIn("Offline mode", report["research"]["reason"])
        # With research skipped, the design is the very first model call.
        self.assertIn("BRIEF", provider.calls[0][1])
        self.assertNotIn("RESEARCH NOTES", provider.calls[0][1])


# ------------------------------------------------------------- real execution


class SandboxedExecutionTests(LabTestBase):
    def setUp(self) -> None:
        super().setUp()
        from babymind import sandbox

        if not sandbox.available():
            self.skipTest("no OS sandbox backend in this environment")

    def test_a_real_language_is_verified_by_measured_execution(self) -> None:
        provider = ScriptedProvider([_design_reply()])
        report = self.lab().run(provider, allow_research=False)

        self.assertEqual(report["status"], "verified", report["reason"])
        self.assertEqual(report["stage"], "adopted")
        conformance = report["conformance"]
        self.assertTrue(conformance["passed"])
        cases = {check["case"]: check for check in conformance["checks"]}
        self.assertTrue(cases["r1"]["passed"])
        self.assertTrue(cases["r1-held-out"]["passed"])
        self.assertTrue(cases["determinism"]["passed"])
        self.assertTrue(cases["invalid-program-rejected"]["passed"])
        self.assertEqual(cases["r1"]["oracle"], "12.35")

        # The interpreter was really written to disk and really run.
        written = Path(report["directory"]) / "interpreter.py"
        self.assertTrue(written.is_file())
        self.assertTrue((Path(report["directory"]) / "probes").is_dir())

    def test_an_interpreter_that_prints_memorised_answers_is_rejected(self) -> None:
        """The decisive test: passing must require a real implementation.

        This interpreter reproduces every declared expectation exactly, so a
        naive conformance check would accept it. The harness's held-out numbers
        are numbers it has never seen, so it fails.
        """
        provider = ScriptedProvider([_design_reply(content=HARDCODED_INTERPRETER)])
        report = self.lab().run(provider, allow_research=False)

        self.assertEqual(report["status"], "rejected")
        cases = {check["case"]: check for check in report["conformance"]["checks"]}
        # The declared cases it memorised do pass...
        self.assertTrue(cases["r1"]["passed"])
        self.assertTrue(cases["r2"]["passed"])
        # ...but the unseen ones do not.
        self.assertFalse(cases["r1-held-out"]["passed"])
        self.assertFalse(cases["r2-held-out"]["passed"])
        self.assertTrue(
            any("unseen number" in failure for failure in report["conformance"]["failures"])
        )

    def test_a_crashing_interpreter_is_rejected(self) -> None:
        provider = ScriptedProvider([_design_reply(content="raise SystemExit(3)\n")])
        report = self.lab().run(provider, allow_research=False)
        self.assertEqual(report["status"], "rejected")
        self.assertTrue(
            any("exited 3" in failure for failure in report["conformance"]["failures"])
        )

    def test_a_verified_language_is_registered_as_a_self_design(self) -> None:
        self.lab().run(ScriptedProvider([_design_reply()]), allow_research=False)
        designs = self.independence.designs.designs(kind="language", limit=5)
        self.assertEqual(len(designs), 1)
        self.assertIn("Numa", designs[0]["title"])
        self.assertIn("Conformance:", designs[0]["proposal"])

    def test_a_rejected_language_is_not_registered_as_a_design(self) -> None:
        self.lab().run(
            ScriptedProvider([_design_reply(content=HARDCODED_INTERPRETER)]),
            allow_research=False,
        )
        self.assertEqual(self.independence.designs.designs(kind="language", limit=5), [])


# ------------------------------------------------------------------ the record


class RecordTests(LabTestBase):
    def test_runs_are_durable_and_audited(self) -> None:
        with mock.patch.object(language_lab, "evaluate_conformance",
                               return_value={"passed": True, "checks": [], "failures": [],
                                             "summary": "0/0"}):
            self.lab().run(ScriptedProvider([_design_reply()]), allow_research=False)
        report = self.independence.language_store.report()
        self.assertEqual(report["runs"], 1)
        self.assertEqual(report["counts"]["verified"], 1)
        self.assertEqual(report["languages"], ["Numa"])
        self.assertTrue(report["audit"]["valid"])
        self.assertEqual(report["audit"]["entries"], 1)

    def test_the_recorded_specification_is_the_one_that_ran(self) -> None:
        with mock.patch.object(language_lab, "evaluate_conformance",
                               return_value={"passed": True, "checks": [], "failures": [],
                                             "summary": "0/0"}):
            report = self.lab().run(ScriptedProvider([_design_reply()]), allow_research=False)
        stored = self.independence.language_store.run(report["run_id"])
        self.assertEqual(stored["spec"]["name"], "Numa")
        self.assertEqual(
            report["spec_hash"], language_lab.spec_digest(language_lab._normalise_spec(make_spec()))
        )

    def test_tampering_with_the_audit_chain_is_detected(self) -> None:
        store = self.independence.language_store
        store.audit("language_verified", {"name": "Numa"})
        store.audit("language_rejected", {"name": "Other"})
        self.assertTrue(store.verify_audit_chain()["valid"])

        db = store._connect()
        try:
            db.execute("UPDATE language_lab_audit SET body=? WHERE id=1",
                       (store.secure.encrypt('{"kind":"changed","at":"x","payload":{}}'),))
            db.commit()
        finally:
            db.close()
        result = store.verify_audit_chain()
        self.assertFalse(result["valid"])
        self.assertEqual(result["broken_at"], 1)

    def test_records_survive_a_new_process(self) -> None:
        with mock.patch.object(language_lab, "evaluate_conformance",
                               return_value={"passed": True, "checks": [], "failures": [],
                                             "summary": "0/0"}):
            self.lab().run(ScriptedProvider([_design_reply()]), allow_research=False)
        reopened = Independence(home=self.home)
        self.assertEqual(reopened.language_store.report()["languages"], ["Numa"])


# -------------------------------------------------------------------- status


class StatusTests(LabTestBase):
    def test_status_separates_what_is_verified_from_what_is_not(self) -> None:
        status = self.lab().status()
        self.assertTrue(status["enabled"])
        self.assertTrue(status["requires_sandbox"])
        self.assertFalse(status["uses_network"] is True)
        self.assertTrue(any("sandbox" in item for item in status["verifies"]))
        self.assertTrue(any("coherent" in item for item in status["does_not_verify"]))
        self.assertIn("records", status)

    def test_status_does_not_create_the_languages_folder(self) -> None:
        self.lab().status()
        self.assertFalse((self.root / "languages").exists())


if __name__ == "__main__":
    unittest.main()
