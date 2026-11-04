"""Tests for truthful workspace and project-execution release gates."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from babymind import approval, sandbox
from babymind.workspace_readiness import workspace_readiness


class WorkspaceReadinessTests(unittest.TestCase):
    def test_report_never_claims_workspace_or_sandbox_is_ready(self) -> None:
        report = workspace_readiness()
        self.assertEqual(report["model_engine"], "llama.cpp")
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["coding_assistant"]["status"], "drafting_only")
        self.assertFalse(report["coding_assistant"]["can_read_workspace"])
        self.assertFalse(report["coding_assistant"]["can_modify_files"])
        self.assertFalse(report["coding_assistant"]["can_run_commands"])
        self.assertFalse(report["native_workspace"]["production_broker"])
        self.assertFalse(report["native_workspace"]["broker_owned_approval"])
        self.assertEqual(report["project_execution"]["sandbox_available"], sandbox.available())
        self.assertEqual(len(report["blockers"]), 4)

    def test_sandbox_report_is_not_hard_coded(self) -> None:
        report = workspace_readiness()
        execution = report["project_execution"]
        self.assertIn(execution["status"], {"sandboxed", "unsandboxed"})
        self.assertEqual(execution["status"] == "sandboxed", execution["sandbox_available"])
        self.assertTrue(execution["sandbox_detail"])
        self.assertIn("environment", execution["sandbox_mechanisms"])
        self.assertFalse(report["local_app_builder"]["os_sandbox"])

    def test_report_reflects_closed_production_file_action_gate(self) -> None:
        with patch.object(approval, "WORKSPACE_FILE_ACTIONS_ENABLED", False):
            report = workspace_readiness()
        self.assertFalse(report["native_workspace"]["file_actions_enabled"])

    def test_report_is_descriptive_and_does_not_change_security_gate(self) -> None:
        original = approval.WORKSPACE_FILE_ACTIONS_ENABLED
        workspace_readiness()
        self.assertIs(approval.WORKSPACE_FILE_ACTIONS_ENABLED, original)


if __name__ == "__main__":
    unittest.main()
