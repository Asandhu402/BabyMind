"""Tests for the audited upstream integration registry."""
from __future__ import annotations

import unittest

from babymind.integrations.upstream_components import upstream_component_report


class UpstreamComponentTests(unittest.TestCase):
    def test_linux_relevant_upstreams_are_mapped_without_enabling_them(self):
        report = upstream_component_report()
        components = report["components"]
        self.assertEqual(
            set(components),
            {"sqlcipher3", "code_symbol_index", "opencode", "atomic_agent", "sandbox_runtime", "ocbox"},
        )
        self.assertEqual(report["policy"]["model_engine"], "llama.cpp")
        self.assertFalse(report["policy"]["cloud_inference_allowed"])
        self.assertFalse(report["policy"]["lm_studio_allowed"])
        self.assertFalse(report["policy"]["host_workspace_tools_enabled"])
        self.assertFalse(report["policy"]["project_execution_enabled"])
        self.assertIn("not trusted runtime dependencies", report["notice"])

    def test_every_upstream_has_repository_role_and_constraints(self):
        for component in upstream_component_report()["components"].values():
            self.assertTrue(component["repository"].startswith("https://github.com/"))
            self.assertTrue(component["role"])
            self.assertTrue(component["constraints"])
            self.assertIn(
                component["integration"],
                {"reference_only", "security_evaluation", "workflow_reference", "experimental_evaluation", "test_only_evaluation"},
            )

    def test_report_is_defensive_copy(self):
        first = upstream_component_report()
        first["components"]["opencode"]["constraints"].clear()
        second = upstream_component_report()
        self.assertTrue(second["components"]["opencode"]["constraints"])


if __name__ == "__main__":
    unittest.main()
