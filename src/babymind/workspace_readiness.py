"""Truthful capability reporting for BabyMind's Linux coding workflow.

This module is descriptive only: it never enables filesystem or process access.
The release gates stay closed until Linux security boundaries are implemented
and independently verified.
"""
from __future__ import annotations


def workspace_readiness() -> dict:
    """Return the currently supported Linux project-workflow capabilities."""
    from . import approval, builder, sandbox as sandboxing, selfdev

    workspace_enabled = bool(approval.WORKSPACE_FILE_ACTIONS_ENABLED)
    app_builder = builder.builder_status()
    development = selfdev.status()
    isolation = sandboxing.status()
    return {
        "platform": "linux",
        "model_engine": "llama.cpp",
        "coding_assistant": {
            "status": "drafting_only",
            "can_read_workspace": False,
            "can_modify_files": False,
            "can_run_commands": False,
        },
        "native_workspace": {
            "status": "not_implemented",
            "file_actions_enabled": workspace_enabled,
            "production_broker": False,
            "broker_owned_approval": False,
            "workspace_acl_provisioning": False,
            "independent_security_review": False,
        },
        "project_execution": {
            "status": "sandboxed" if isolation["available"] else "unsandboxed",
            "sandbox_available": isolation["available"],
            "sandbox_backend": isolation["backend"],
            "sandbox_detail": isolation["detail"],
            "sandbox_mechanisms": isolation["mechanisms"],
            "network_isolation": bool(isolation["available"]) and
            "not enforced" not in isolation["mechanisms"].get("network", ""),
            "resource_limits_enforced": isolation["available"],
        },
        "local_app_builder": {
            "status": "opt_in" if app_builder["ready"] else "disabled",
            "enabled": app_builder["enabled"],
            "ready": app_builder["ready"],
            "root": app_builder["root"],
            "writes_only_inside_apps_folder": True,
            "runs_shell_commands": False,
            "os_sandbox": isolation["available"],
            "requires_reviewed_plan_hash": True,
        },
        "mission_control": {
            "roles": 50,
            "phases": 9,
            "models_in_use": 1,
            "records_every_role": True,
            "runs_roles_in_parallel": False,
            "notice": "50 role passes over one local model, scheduled sequentially when hardware is limited.",
        },
        "self_development": {
            "status": "enabled" if development["enabled"] else "disabled",
            "root": development["root"],
            "can_write_source": development["can_write_source"],
            "checkpoints": development["automatic_rollback"],
            "automatic_verification": development["automatic_verification"],
            "automatic_rollback": development["automatic_rollback"],
            "requires_per_change_approval": False,
            "os_sandbox": development["isolation"]["os_sandbox"],
        },
        "release_ready": False,
        "blockers": [
            "Linux-native workspace broker, descriptor-relative operations, and adversarial filesystem tests are incomplete.",
            "Broker-owned, single-use approval and independent Linux security review are incomplete.",
            "The coding assistant is not yet connected to authorized workspace read/write operations.",
            "The Linux execution sandbox must be validated on supported distributions and kernel configurations.",
        ],
        "notice": (
            "Linux-only read-only readiness report. It does not enable workspace "
            "access, file changes, command execution, or project test execution."
        ),
    }
