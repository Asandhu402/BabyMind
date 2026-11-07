# Autonomous platform audit

BabyMind is **not** a fully autonomous development platform or release-ready
security boundary. This is a status summary, not an acceptance report.

- The 50 specialist roles are sequential prompts over one shared model, not
  independent workers. Recorded model contributions are not proof of completed
  work. Reviews and mission control are separate workflows.
- The source self-development engine has checkpoints, compile/test checks and
  rollback, but its isolation depends on the Linux namespace backend. `auto`
  can fall back to unsandboxed execution; `require` fails closed. The frozen
  desktop cannot run its Python namespace helper or self-development edits.
- The opt-in app builder now runs generated Python only through the shared
  sandboxed runner (`runner.run_command` with `sandbox="require"`): Linux
  user/mount/PID/network namespaces, no network, and CPU/file-size/memory
  (RLIMIT_AS)/process (RLIMIT_NPROC) limits. When no OS sandbox backend is
  available, running generated code is refused (fail closed). It still cannot
  run generated code in the portable app. Review code regardless.
- The verified learning cycle is now supervised permanently: enabled by default,
  durable across restarts, restartable with the Linux user service, serialized by
  cross-process locks and stopped by a durable kill switch, pause, circuit breaker
  or closed gate. It reuses the checkpoint/compile/test/rollback transaction and
  `sandbox=require`; its path guard refuses supervisor, verification, isolation,
  UI, test and model-boundary files. Weakness discovery and effectiveness remain
  model-generated, packaged builds edit staged source only, and the running
  executable is never updated. See [permanent autonomous learning](AUTONOMOUS_LEARNING.md).
- The new **language lab** runs a complete development cycle on an artefact
  that is not this repository: research (opt-in), design a new language,
  validate the specification, execute the generated interpreter in the OS
  sandbox, and compare its output with an oracle recomputed by the harness.
  Held-out numbers derived by the harness defeat an interpreter that only
  prints memorised answers. The limits are exact: design and research are
  model-generated, only decimal rounding is independently checkable, no
  real-model or desktop-UI cycle has been run here, and it is off by default
  and fails closed without a sandbox. See [language lab](LANGUAGE_LAB.md).
- There is still no *formally verified* security boundary, but all untrusted
  execution now funnels through one broker (`babymind.broker.execute`, exposed
  at `/api/broker/status`) with a fail-closed `sandbox=require` policy and an
  auditable decision log. Same-user processes are still not sandboxes.
  Adversarial escape probes live in `tests/test_sandbox_escape.py` (host file
  access, proc-based escapes, ptrace of host pids, unix sockets, network,
  module loading). Nested-sandbox operation (BabyMind inside a container/VM)
  is detected and reported but inner namespaces remain weaker than a
  non-nested boundary. Checkpoints do not back up databases, keys, the model
  or every Git state.
- Local llama.cpp, the pinned model and Linux packaging exist, but real GUI,
  model download and inference acceptance have not been completed in this
  environment. See [Linux verification](LINUX_VERIFICATION.md).
- GitHub research is read-only and inspected source is untrusted; license and
  supply-chain review is not automatic. Optional integrations require separate
  installation and verification.

Remaining gates include a reviewed execution and workspace boundary, recovery
and installation acceptance, real-model tests (the real-model CI job now
runs automatically on every push and pull request instead of on request —
configured for Ubuntu 26.10 in the morning of 2026-11-06 and moved the same
day to the hosted Ubuntu 26.04 LTS runner; its last recorded run failed, so a
passing real-model acceptance is still an
open gate), desktop/UI testing and target hardware performance. The learning
supervisor's scheduler, gates, locks, controls, guard, API/CLI/UI and installer
have scripted tests, but real-model and long-running desktop acceptance remain
open gates. No model independence, sandbox escape resistance, or general fully
autonomous development is claimed; the permanent learning process is a bounded,
audited, stoppable verified cycle, not a finished autonomous engineer.
