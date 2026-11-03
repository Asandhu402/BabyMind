"""Tests for safe user-facing model output and grounded self-review reports."""

import unittest

from babymind.response_quality import (
    strip_internal_reasoning,
    validate_code_review_report,
)


class ResponseQualityTests(unittest.TestCase):
    def test_removes_complete_think_block_and_keeps_final_answer(self):
        self.assertEqual(
            strip_internal_reasoning("<think>private reasoning</think>\nThe answer is 42."),
            "The answer is 42.",
        )

    def test_removes_unclosed_think_block(self):
        self.assertEqual(
            strip_internal_reasoning("Useful preface. <think>unfinished private reasoning"),
            "Useful preface.",
        )

    def test_rejects_response_containing_only_internal_reasoning(self):
        with self.assertRaisesRegex(ValueError, "no user-facing answer"):
            strip_internal_reasoning("<think>private reasoning only</think>")

    def test_accepts_report_with_exact_source_line_and_required_sections(self):
        source = "def answer():\n    return 'ok'\n"
        report = """Finding
The function returns a fixed value.
Evidence (line 2): `return 'ok'`
Recommended fix
Return the validated result instead.
Tests
Test a valid value and an empty value.
Acceptance criteria
Both tests pass and invalid input is rejected."""
        validate_code_review_report(report, source)

    def test_rejects_fabricated_line_evidence(self):
        source = "def answer():\n    return 'ok'\n"
        report = """Finding
The function returns a fixed value.
Evidence (line 99): `return 'fake'`
Recommended fix
Validate the result.
Tests
Test normal and empty values.
Acceptance criteria
Both tests pass."""
        with self.assertRaisesRegex(ValueError, "exact source line"):
            validate_code_review_report(report, source)

    def test_rejects_incomplete_report(self):
        with self.assertRaisesRegex(ValueError, "missing sections"):
            validate_code_review_report("Finding: nothing else.", "x = 1\n")


if __name__ == "__main__":
    unittest.main()
