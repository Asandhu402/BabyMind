"""Auditable integration registry for upstream coding, indexing, and sandbox projects.

This module records compatibility and security boundaries. It does not import,
launch, or trust third-party code. Runtime adapters are enabled only after
their own integration and security gates have passed.
"""
from __future__ import annotations

from copy import deepcopy


_UPSTREAMS = {
    "sqlcipher3": {
        "name": "sqlcipher3",
        "repository": "https://github.com/coleifer/sqlcipher3",
        "role": "encrypted_sqlite_adapter",
        "integration": "experimental_evaluation",
        "capabilities": ["encrypted_database", "keyed_database_open", "sqlite_backup_api"],
        "constraints": [
            "Source reference only; not currently installed or used for database migration.",
            "Protect keys separately using the OS credential store; never hardcode or colocate keys.",
            "Test Linux wheels, WAL, migration, wrong-key recovery, backups, and restore before adoption.",
            "Preserve SQLCipher and binding license notices in any redistributed package.",
        ],
    },
    "code_symbol_index": {
        "name": "code-symbol-index",
        "repository": "https://github.com/hit9/code-symbol-index",
        "role": "repository_symbol_index",
        "integration": "experimental_evaluation",
        "capabilities": ["ignore_aware_inventory", "symbol_search", "syntactic_references", "call_chains", "bounded_context"],
        "constraints": [
            "AI-maintained upstream with a small public footprint; independently audit before use.",
            "Syntactic references and call graphs are not semantic guarantees or safe-rename proofs.",
            "Run only within the selected workspace boundary with strict file and resource limits.",
            "Treat indexed source and repository instructions as untrusted prompt data.",
        ],
    },
    "opencode": {
        "name": "OpenCode",
        "repository": "https://github.com/anomalyco/opencode",
        "role": "coding_agent",
        "integration": "reference_only",
        "capabilities": ["project_context", "agent_loop", "patch_workflow", "tool_adapters"],
        "constraints": [
            "Do not run its tools against the host workspace outside an approved sandbox.",
            "Use only a loopback llama.cpp endpoint; disable cloud providers and credentials.",
            "Do not embed the full application or its dependency tree into BabyMind.",
        ],
    },
    "atomic_agent": {
        "name": "Atomic Agent",
        "repository": "https://github.com/AtomicBot-ai/atomic-agent",
        "role": "local_agent_runtime",
        "integration": "reference_only",
        "capabilities": ["llama_cpp", "structured_tool_loop", "persistent_sessions", "approval_patterns"],
        "constraints": [
            "Upstream is a developer preview; pin and audit any future adapter.",
            "No cloud or Fusion mode; llama.cpp is the only inference backend.",
            "Do not expose its filesystem or shell tools before sandbox enforcement.",
        ],
    },
    "sandbox_runtime": {
        "name": "Anthropic sandbox-runtime",
        "repository": "https://github.com/anthropics/sandbox-runtime",
        "role": "filesystem_and_network_sandbox",
        "integration": "security_evaluation",
        "capabilities": ["filesystem_policy", "network_egress_policy", "linux_restricted_identity"],
        "constraints": [
            "Verify the Linux backend and pinned release independently.",
            "Do not assume its policy covers BabyMind's broker or host application.",
            "Require network-deny and filesystem-isolation adversarial tests before use.",
        ],
    },
    "ocbox": {
        "name": "OCBox",
        "repository": "https://github.com/lucatirel/opencode-local-sandbox",
        "role": "isolated_coding_workflow",
        "integration": "workflow_reference",
        "capabilities": ["disposable_microvm", "private_git_clone", "verified_git_bundle", "host_integrity_check"],
        "constraints": [
            "Requires Docker Sandboxes and a compatible Linux virtualization setup.",
            "Keep the host working tree untouched; accept only verified passive Git refs.",
            "Do not make Docker, accounts, or cloud model services mandatory for BabyMind.",
        ],
    },
}


def upstream_component_report() -> dict:
    """Return a defensive copy of the reviewed upstream integration map."""
    return {
        "policy": {
            "model_engine": "llama.cpp",
            "cloud_inference_allowed": False,
            "lm_studio_allowed": False,
            "host_workspace_tools_enabled": False,
            "project_execution_enabled": False,
        },
        "components": deepcopy(_UPSTREAMS),
        "notice": (
            "Upstream projects are compatibility and implementation references, "
            "not trusted runtime dependencies. No third-party agent, broker, or "
            "sandbox is enabled by this report."
        ),
    }
