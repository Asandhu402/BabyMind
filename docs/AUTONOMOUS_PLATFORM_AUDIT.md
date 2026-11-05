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
- There is no production workspace broker or independently verified security
  boundary. Same-user processes are not sandboxes; the builder and
  self-development engine share the one sandboxed runner, but that is a single
  choke point, not a verified broker. Checkpoints do not back up databases,
  keys, the model or every Git state.
- Local llama.cpp, the pinned model and Linux packaging exist, but real GUI,
  model download and inference acceptance have not been completed in this
  environment. See [Linux verification](LINUX_VERIFICATION.md).
- GitHub research is read-only and inspected source is untrusted; license and
  supply-chain review is not automatic. Optional integrations require separate
  installation and verification.

Remaining gates include a reviewed execution and workspace boundary, recovery
and installation acceptance, real-model tests, desktop/UI testing and target
hardware performance. No model independence, sandbox escape resistance, or
fully autonomous work is claimed.
