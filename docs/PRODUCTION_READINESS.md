# Production readiness programme

**Status: engineering programme and acceptance contract; not a claim of production readiness.**

BabyMind must earn production status through repeatable evidence on a clean,
supported Linux installation. A successful unit-test run, a completed 50-role
mission, or a model-generated claim is not acceptance evidence by itself.

Gate items below are tagged: **[implemented]** (code exists), **[partial]**
(some behaviour exists but gaps remain), **[verified]** (covered by automated
tests/escape probes, not just code review). "Implemented" never implies
"verified".

## Product objective

Build a local-first Linux AI software engineer that can understand a user's
goal, inspect an authorized workspace, plan and execute bounded work, run
independent checks, repair failures, explain its changes, and recover safely.
It should support ordinary question answering and research as separate modes.

The system must remain useful offline for local-model tasks. Network research,
dependency retrieval, and GitHub operations are explicit capabilities with
separate policy and audit controls.

## Non-negotiable invariants

1. **Least privilege:** every tool has a narrow capability, workspace, and
   lifetime. No agent can grant itself permissions or expand another agent's
   authority.
2. **Untrusted input:** prompts, repository files, issues, web pages, model
   output, and tool output are data, never authority-bearing instructions.
3. **Execution isolation:** generated or third-party code never runs with the
   user's ambient privileges. Fail closed if the configured isolation backend
   is unavailable.
4. **Human control:** provide a visible stop control, bounded budgets, and
   approval gates for destructive, external, financial, credential, or
   irreversible actions. Routine reversible workspace edits can be automated
   within the user's explicit project scope.
5. **Evidence over claims:** a role contribution is not proof. Every claimed
   action must link to tool events, artifacts, test results, or an explicit
   statement that it was not performed.
6. **Recoverability:** use versioned worktrees/checkpoints, durable audit
   records, verified restore procedures, and backups independent of the
   workspace being modified.
7. **No silent privilege escalation:** agents cannot modify policy, sandbox
   configuration, allowlists, secrets, or their own authority as part of a task.
8. **Bounded operation:** enforce wall-clock, token, tool-call, retry, disk,
   memory, and process limits at the runtime boundary.

## Release gates

A release is blocked until every applicable gate has an attached reproducible
artifact and an owner-approved result.

### G0 — Supported installation and lifecycle

- Fresh Debian and Ubuntu-family x86-64 desktop install, upgrade, launch,
  restart, uninstall, and reinstall tests, tested on Ubuntu 26.04 LTS and including
  the glibc floor the portable archive is built against.
- Reproducible, signed release artifacts and a published software bill of
  materials; pinned and verified model/runtime/dependency downloads.
- No network dependency after the model and declared offline assets are cached.
- Backup and restore tested for databases, encryption keys, settings, model
  metadata, and user workspaces.

### G1 — Runtime and workspace broker

- One broker is the only path to process execution and privileged workspace
  commands **[implemented, verified]** (`broker.execute`, decision log at
  `/api/broker/status`); browser and GitHub *action* capabilities remain
  read-only **[partial]**.
- Per-task capability grants are scoped to exact paths, operations, hosts,
  and expiry; deny by default.
- Workspace operations reject traversal, symlink races, special files, and
  writes outside the approved root.
- Commands run in a separately verified Linux isolation boundary with
  resource limits (CPU/FSIZE/NOFILE/RLIMIT_AS/RLIMIT_DATA/NPROC, with
  `LIMIT_FAILED` reporting, plus best-effort cgroup v2 `memory.max` when
  delegated), network policy, process cleanup, and a disposable tmpfs root
  **[implemented, verified]**. Guaranteed physical-memory cgroup caps and
  per-kernel escape-probe matrices remain **[partial]**.
- Self-development edits can be pre-verified in a disposable `git worktree`
  (`BABYMIND_SELF_EDIT_WORKTREE=true`) before the primary checkout is touched
  **[implemented, verified]**; making worktrees the *default* edit path remains
  **[partial]**.
- Sandbox self-tests include adversarial escape attempts
  (`tests/test_sandbox_escape.py`) **[implemented, verified]** on this
  kernel/container configuration.
- If isolation cannot be verified, generated code execution and self-edit are
  disabled rather than downgraded to same-user subprocess execution.

### G2 — Reliable agent runtime

- Explicit task graphs with dependency scheduling, bounded parallelism, and
  HTTP cancellation exist (`taskgraph.py`, `/api/taskgraph/run`,
  `/api/taskgraph/cancel`, graph mode in missions) **[implemented, verified]**;
  typed inputs/outputs and durable graph state remain **[partial]**.
- Distinguish planner, researcher, coder, executor, verifier, and approver
  capabilities. Agents receive only the tools needed for their role.
- Require schema-validated outputs; malformed output is a typed failure, not
  an implicit success.
- Independent verification runs compile, the full test suite, a sandboxed
  runtime-behavior check, live sandbox escape probes, and (with a brief) an
  acceptance-judgement record — model self-attestation never passes a gate
  (`verifier.py`, `/api/verify/run`) **[implemented, verified]**; security-
  scanner integration remains **[partial]**.
- Track provenance for every assertion and action, including source URLs,
  commit IDs, file diffs, command records, and test artifacts.
- Support resumable missions and deterministic handling of retries, timeouts,
  cancellation, and partial completion.

### G3 — Software engineering loop

- Work in disposable Git worktrees or equivalent isolated copies; never edit
  the user's primary checkout by default.
- Inspect project instructions and build systems as untrusted data.
- Build a repository map, identify test commands, and establish a baseline
  before changing files.
- Apply minimal patches; run focused tests, full tests, type/lint/security
  checks, and application-level behavior tests as appropriate.
- On failure, capture logs, diagnose, make bounded repairs, and rerun the
  failing test plus regression suite.
- Produce a reviewable diff, change summary, known risks, and exact
  reproduction commands.
- Promote changes only after policy checks and the configured approval gate.

### G4 — Model and answer quality

- Evaluate the pinned production model on a versioned task suite for factual
  QA, coding, debugging, planning, tool selection, citation accuracy,
  refusal behavior, and multilingual use.
- Measure task success, regression rate, hallucinated tool claims, malformed
  outputs, latency, memory use, and resource exhaustion.
- Compare model upgrades against a fixed baseline; do not silently replace a
  model or change its prompt contract.
- Support model profiles based on available hardware, with clear quality and
  performance expectations.

### G5 — Security and privacy

- Threat model prompt injection, malicious repositories, dependency
  confusion, tool misuse, data exfiltration, local privilege escalation,
  denial of service, and compromised updates.
- Add adversarial tests for indirect prompt injection and malicious tool
  outputs at every trust boundary.
- Keep secrets out of prompts, model context, logs, crash reports, and
  untrusted subprocess environments.
- Authenticate local APIs, enforce origin/host checks, rate limits, CSRF
  protections, and safe LAN defaults.
- Add dependency scanning, SBOM generation, secret scanning, static analysis,
  and a documented vulnerability response process.
- Conduct an independent security review before claiming production security.

### G6 — Operations and observability

- Structured, tamper-evident event logs with redaction and retention controls.
- Health checks for model, storage, sandbox, integrations, and update state.
- User-visible mission status, active tool calls, budget consumption, and
  stop/cancel behavior.
- Crash-safe transactions, restart recovery, and fault-injection tests.
- Documented support bundle export that excludes secrets and private content
  by default.

## Required release evidence

Every release candidate must publish:

- Exact source commit and build environment.
- Signed artifact hashes and SBOM.
- Clean-install and upgrade test reports on supported Ubuntu versions.
- Full unit/integration/end-to-end test reports with skipped tests explained.
- Real-model evaluation results, including failed cases.
- Sandbox adversarial test report and resource-limit measurements.
- Backup/restore and crash-recovery test reports.
- Security review status and known-issues register.

## Current known blockers

Based on the repository's current `AUTONOMY.md`,
`AUTONOMOUS_PLATFORM_AUDIT.md`, `KNOWN_LIMITATIONS.md`, and
`LINUX_VERIFICATION.md`:

- The 50 roles are role-guided prompts over one shared small local model, not
  independently capable agents. Sequential mode remains the default; a
  phase-parallel task-graph mode (`mode="graph"`, `/api/taskgraph/run`) exists
  **[implemented, verified]**, now with typed task inputs, HTTP cancellation,
  and durable resumable graph state (`TaskGraphStore`) **[implemented,
  verified]**; typed output schemas remain **[partial]**.
- The runner is not itself an OS boundary; all privileged execution goes
  through the broker into the Linux namespace sandbox
  **[implemented, verified]**, with adversarial escape probes
  (`tests/test_sandbox_escape.py`). The `auto` sandbox mode now fails closed
  unless `BABYMIND_ALLOW_UNSANDBOXED_AUTO=true` **[implemented, verified]**.
- The sandbox still has documented nested-isolation limits (detected and
  reported, but single-layer) and uses rlimits rather than cgroup memory caps
  (RLIMIT_AS/RLIMIT_DATA cap virtual memory, not physical RAM)
  **[partial]**.
- Packaged self-edit stages source but does not build, promote, restart, or
  activate an updated application; the upgrade path copies the staged source
  into the package seed with a backup **[implemented]**; generated app
  execution in the portable package remains disabled (fail closed).
- The production model has only limited real-world acceptance evidence; role
  outputs have included unsupported claims, and a real-source self-edit test
  has failed on malformed JSON. That failure traced to two BabyMind defects -
  a JSON extractor that rejected the raw newlines small models emit inside
  string values, and a repair loop that gave up on the first unparseable reply
  instead of retrying - both now fixed and covered by regression tests, but a
  passing hosted real-model self-edit is still outstanding.
- Clean desktop acceptance, signed releases, auto-update, and independent
  security assessment are not complete. The fulfilment review in
  `verifier.py` is preliminary (same shared model), not independent
  inspection.

These blockers must be fixed in code and verified; changing documentation or
renaming components does not close a gate.

## Delivery sequence

1. Make execution and workspace access fail-closed behind a single broker.
2. Add adversarial sandbox tests and enforce resource limits, including memory.
3. Complete the task-graph runtime: typed inputs/outputs, durable/resumable graph state (parallel graph mode already exists).
4. Build the worktree-based coding loop and independent verification pipeline.
5. Add real-model evaluation, failure analysis, and regression thresholds.
6. Complete packaging, signed updates, backup/restore, observability, and
   independent security review.

**Definition of done:** all release gates pass on supported clean Linux
machines, all evidence is reproducible from a tagged commit, and no critical
or high-severity security issue remains open. Until then BabyMind must identify
itself as experimental/development software, not production-ready autonomous AI.

## Engineering references

- [Canadian Centre for Cyber Security: Careful adoption of agentic AI](https://www.cyber.gc.ca/en/guidance/careful-adoption-agentic-ai)
- [OWASP AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html)
- [NIST AI Risk Management Framework](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10)
- [OWASP Artificial Intelligence Security Verification Standard](https://owasp.github.io/www-project-artificial-intelligence-security-verification-standard-aisvs-docs/)
