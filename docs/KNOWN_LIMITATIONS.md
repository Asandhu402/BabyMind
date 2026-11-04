# Known limitations

This file exists so no capability is over-claimed. Each item names what is
missing, not what is planned.

## Platform and packaging

- **Windows is unverified in this build.** The code paths are written for
  Windows 10/11, but the test run recorded in `docs/TEST_REPORT.md` was executed
  on Linux. Windows-only behaviour (Job Objects, DPAPI, `taskkill /T`, portable
  packaging, installer, autostart) has not been run here.
- **No installer or updater ships from this session.** The release workflow
  produces a portable ZIP; there is no auto-update channel, no code signing, and
  no separate supervisor process that can repair a broken installation.
- macOS and Linux builds of the desktop shell are not produced.

## Sandboxing and execution

- **The OS sandbox is Linux-only today.** `sandbox.py` builds a user, mount,
  pid and network namespace, chroots into a tmpfs root, mounts the system
  read-only, mounts only the project writable, and drops the network to
  loopback. `self_test()` proves each of those four claims against the live
  kernel, and the sandboxed suite runs the same green result as an unsandboxed
  one.
- **No Windows or macOS backend exists.** `sandbox.backend()` returns
  `available: false` with the reason (`AppContainer/Job Object backend not
  implemented`, `sandbox-exec backend not implemented`). `BABYMIND_SANDBOX=require`
  then refuses to run commands at all, and the default `auto` mode records
  `sandbox: "unavailable"` on every result instead of claiming isolation.
- **Nested sandboxes fail closed to plain execution.** The kernel forbids user
  namespaces inside a user namespace, so a verification run started *by* a
  sandboxed process reports the backend as unavailable and executes inside the
  existing namespace. That is still contained, but it is one layer, not two.
- **Limits are rlimits, not cgroups.** CPU time, file size and open files are
  capped; memory is not, because cgroup delegation is unavailable here. A runaway
  allocation inside the sandbox is bounded by the parent's monitor and timeout,
  not by the kernel.
- **Only the project root is writable, and that includes `state/`.** The sandbox
  protects your home directory, keys and the network, not the project's own
  files: a model-authored patch can still damage the checkout it is editing,
  which is what checkpoints and rollback are for.

## Autonomy

- **50 roles are 50 prompts over one model**, executed sequentially by default.
  There is no multi-model parallelism, no debate protocol beyond the shared
  digest, and no learned routing.
- A mission only edits source when started with `self_edit: true`. The loop then
  applies **one** patch proposed by the Coding Agent role, verified by compile
  and tests. It is not an iterative engineer: it does not read the failure,
  repair its own patch, and retry within the same mission.
- The patch comes from a 4B-class local model. Expect small, local changes, not
  architectural rewrites.
- Missions stop at the time budget. Unrun roles are recorded as `deferred`; they
  are not retried automatically.
- The model is a 4B-class local GGUF. Long briefs and deep architectural
  reasoning will exceed it. Quality depends on the model you install.

## Self-development

- Verification is `compileall` plus the repository's unittest suite. A change
  that passes both but is semantically wrong is kept.
- Checkpoints copy project files; they do not snapshot the Git index, untracked
  binaries, databases, keys, or the model. They are not backups of user data.
- The engine refuses protected paths (`.git`, keys, databases, binaries) but it
  edits with your user's privileges; it is not protection against a compromised
  process.
- `BABYMIND_RUNNER_UNRESTRICTED` exists, is off by default, and removes the
  executable allowlist. Leaving it on is equivalent to giving the engine a shell.

## Applications BabyMind can build

- The app builder produces Python/HTML/CSS/JS applications inside a folder. It
  does not compile C#/Java/Rust/Go projects, sign mobile apps, produce iOS
  builds (requires macOS and Xcode), or submit anything to a store.
- Nothing is installed system-wide; generated apps run from their folder.
- Dependency installation for generated projects is not automated.

## Data and model

- No model is bundled in the repository. First launch downloads ~2.7 GB, and
  that download has not been exercised in this environment.
- Conversations, missions, and memory are encrypted at rest with a key protected
  by DPAPI on Windows. That protects the files when the app is closed; it does
  not protect a running session or a compromised user account.
- Knowledge-graph and voice integrations remain optional and unverified here.

## Interface

- The mission and self-development views were syntax-checked and served by the
  test server, but were not driven through a real browser in this environment.
- There is no diff viewer beyond the text `diff` field, no terminal emulator, and
  no project explorer tree in the UI yet (the API exposes `/api/dev/tree`).
