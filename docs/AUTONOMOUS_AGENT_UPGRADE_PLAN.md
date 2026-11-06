# Autonomous and Collaborative Agent Upgrade Plan

**Status:** proposal / implementation plan. This document does not claim that the proposed capabilities are implemented.

## Product goal

Evolve BabyMind into a local-first Linux AI engineering workspace that can take an authorized project goal through research, planning, implementation, verification, bounded repair, and delivery. Multiple specialist agents should be able to collaborate on that work without sharing unrestricted authority.

The system must remain useful with one local model and no network connection. Optional additional local or remote model backends may improve collaboration, but remote services must be opt-in and separately permissioned.

## What exists today

The current codebase already provides important foundations:

- `orchestrator.py`: role-guided mission phases and contribution records.
- `taskgraph.py`: dependency-validated DAG execution, bounded parallelism, cancellation, and resumable graph checkpoints.
- `MissionStore` and `LocalMemory`: encrypted local mission and opt-in memory storage.
- `broker.py`, `runner.py`, and `sandbox.py`: a central execution path, command policy, and fail-closed Linux sandbox.
- `verifier.py`: compile/test/runtime/security checks and a preliminary fulfilment review.
- `selfdev.py`: checkpointed source edits, verification, rollback, and audit records.

These are foundations, not proof of unrestricted autonomy. The current 50 roles are prompts over one shared model. Multiple role prompts do not constitute independent models, independent verification, or independent agents.

## Target mission lifecycle

A mission should move through explicit, inspectable states:

1. **Intake** — normalize the user's goal, identify the authorized workspace, constraints, and required approvals.
2. **Baseline** — map the repository, read project instructions as untrusted data, detect build/test commands, record the clean/dirty worktree state, and run baseline checks.
3. **Plan** — produce a schema-validated plan with task IDs, owners, dependencies, expected artifacts, risk levels, budgets, and acceptance criteria.
4. **Research and design** — gather evidence and record source provenance; separate facts from assumptions.
5. **Execute** — run independent DAG tasks concurrently only when dependencies and resource budgets allow.
6. **Review** — run a critic/reviewer pass with explicit access to the diff and test evidence. Label whether the reviewer uses the same model/weights as the implementer; same-model review is useful but not independent verification.
7. **Verify** — run focused tests, full tests, static/security checks where configured, runtime tests, and requirement checks. Tool output and artifacts, not model self-attestation, determine pass/fail.
8. **Repair** — allow a small configurable retry budget. Every repair must be tied to a concrete failure and rerun the failing test plus relevant regression suite.
9. **Approve and deliver** — request human approval for destructive, external, credential, financial, irreversible, or policy-changing actions. Present a diff, evidence, limitations, and exact reproduction commands.
10. **Recover** — resume from durable checkpoints without replaying completed side effects; provide a visible cancel/stop path.

## Agent collaboration model

### Agent contract

Each agent should have a stable identity and a typed contract:

- role and objective;
- input schema and output schema;
- allowed capabilities and exact resource scope;
- model/provider identity and model version;
- token, time, tool-call, and retry budgets;
- required evidence and completion conditions.

An agent's declared capability is not permission. The runtime must enforce grants at each tool boundary.

### Collaboration protocol

- The planner creates a DAG; agents do not self-assign unrestricted work.
- Independent research/design/implementation tasks may run in parallel.
- Shared-file edits must be serialized or isolated in separate worktrees and reconciled by a merge/review step.
- Agents exchange structured findings with evidence references, not unbounded conversation transcripts.
- A reviewer must state conflicts, missing evidence, and uncertainty.
- The orchestrator records which model/provider produced each contribution.
- If all agents use the same model weights, the UI and report must say so. Do not call that independent consensus.
- A true independent review may use a separately configured model/provider or deterministic tools. Remote providers are disabled unless the user explicitly configures them.

## Security and control invariants

The existing production-readiness contract remains authoritative. In particular:

- Repository files, issue comments, web pages, model output, and tool output are untrusted data, never instructions that grant authority.
- Agents cannot grant themselves capabilities or change sandbox, allowlist, secret, approval, or policy settings.
- Generated and third-party code runs only through the broker with a verified OS sandbox; fail closed when unavailable.
- Network, GitHub writes, dependency installation, and external side effects require explicit capability grants.
- Secrets must not enter prompts, logs, or untrusted subprocess environments.
- Work is performed in disposable worktrees by default; the primary checkout is not modified until promotion is approved.
- Persisted task state is versioned and tied to a graph/input fingerprint. Completed external side effects need idempotency keys or explicit reconciliation before resume.
- Enforce wall-clock, token, tool-call, retry, process, output, disk, and memory budgets at runtime boundaries.
- Human approval is required for destructive or irreversible actions and for policy/permission changes.

## Implementation sequence

### Phase A — Make existing autonomy measurable

- Define versioned schemas for mission plans, task records, tool events, agent contributions, verification reports, and delivery summaries.
- Persist model/provider/version, prompt-contract version, input hash, task attempt, and evidence references for each contribution.
- Add deterministic state-transition validation and explicit terminal outcomes: completed, partially completed, failed, cancelled, blocked, or awaiting approval.
- Make every task's resource and permission budget visible and enforce it.
- Add fault-injection tests for crash/restart, cancellation, duplicate delivery, stale checkpoints, and partial side effects.

### Phase B — Safe collaborative execution

- Add a provider-neutral model adapter interface while retaining the current local llama.cpp provider as the default.
- Add per-agent model routing configuration; no provider is silently enabled.
- Add structured handoffs: plan, research finding, implementation patch, review finding, and verification evidence.
- Execute independent DAG tasks in isolated worktrees; serialize conflicting edits and verify the merged result.
- Add a reviewer policy that records independence level (same model, different model, or deterministic tool).
- Add disagreement handling: request evidence, run a targeted test, or stop for human decision rather than voting on unsupported claims.

### Phase C — Complete engineering loop

- Add repository mapping and baseline detection.
- Detect project-specific build, lint, type, test, and security commands from trusted configuration plus user approval.
- Implement bounded failure diagnosis and repair with per-failure retry limits.
- Require test reproduction before a repair is accepted.
- Produce a reproducible delivery bundle: patch/diff, test logs, provenance, risk summary, and rollback instructions.
- Promote from disposable worktree only after configured acceptance gates and approval.

### Phase D — Model and product quality

- Create a versioned benchmark suite for planning, tool selection, coding, debugging, safe refusal, source attribution, and multilingual tasks.
- Measure success rate, regressions, false tool claims, malformed outputs, latency, memory, and token usage.
- Compare model changes against a fixed baseline; model replacement is never automatic.
- Provide hardware-aware model profiles and clearly state quality/performance trade-offs.

## Required acceptance tests

A phase is not complete until automated tests demonstrate:

1. A multi-step project task is decomposed into a valid DAG, independent tasks overlap, and dependencies receive only completed prerequisite outputs.
2. Two configured agents can exchange schema-valid findings with provenance and explicit model identities.
3. A same-model reviewer is labelled non-independent; an independently configured reviewer is labelled separately and cannot grant permissions.
4. A malicious repository instruction cannot expand tool permissions, expose secrets, or disable sandbox policy.
5. A generated command is denied when its capability, path, host, budget, or approval is missing.
6. A failed test is captured, diagnosed, repaired within a bounded retry budget, and the failing test is rerun.
7. A crash after a task completes resumes without duplicating a non-idempotent side effect.
8. Cancellation stops pending tasks and records the real outcome of already-running tasks.
9. A conflicting pair of file edits is isolated and resolved before merge; the primary checkout remains untouched until promotion.
10. A failed verification restores the prior worktree/checkpoint and leaves an auditable record.
11. An offline mission works with only the local model and cached assets; network access is denied unless explicitly granted.
12. The final delivery report links every important claim to a diff, command, test result, or source.

## First implementation slice

The safest first code slice should be Phase A, not an unbounded "self-improving AI" rewrite:

- introduce versioned typed records for task/agent execution;
- record model identity and independence level;
- validate mission state transitions;
- make per-task budgets and capability grants explicit;
- add restart/idempotency/fault-injection tests around the existing `TaskGraphStore`.

This strengthens the current runtime without weakening the sandbox or pretending the 50 role prompts are separate minds.
