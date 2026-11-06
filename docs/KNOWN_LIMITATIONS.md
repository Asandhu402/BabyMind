# Known limitations

This file exists so no capability is over-claimed. Each item names what is
missing, not what is planned.

## Platform and packaging

- The supported portable target is Debian-based Linux on x86-64 with glibc 2.43+ (Ubuntu 26.04+; the release is built and tested on Ubuntu 26.10). Debian 13 ships glibc 2.41 and is below the portable-archive floor, though source builds with Python 3.13+ remain supported there. Python 3.13+ is required for source builds, along with a graphical desktop. Historically, a hosted Ubuntu 22.04 VM with Xvfb passed the installer, real model download and one GUI chat response while BabyMind still supported Python 3.10/3.11; that combination is no longer supported. A clean Ubuntu Desktop session and broader capabilities remain unverified.
- The one-command installer is exercised in CI configured for Ubuntu 26.10
  (bootstrap preparation, Qt build and packaged app). Debian and Ubuntu
  derivatives are the only supported distribution family. GitHub does not
  publish a hosted `ubuntu-26.10` runner label yet, so these jobs require a
  self-hosted Ubuntu 26.10 runner (see
  [testing on Ubuntu 26.10](UBUNTU_26_10_TESTING.md)); until one is registered
  they remain queued. A fresh-machine run with the production model remains
  unverified.
- There is no auto-updater, code signing, or self-repair supervisor.
- Linux x86-64 is the sole supported desktop target.
- The portable executable is not itself a Python interpreter. A bundled Python helper supports sandboxed staged-source tests; generated Python app execution is still unavailable.

## Sandboxing and execution

- **The OS sandbox is Linux-only today.** `sandbox.py` builds a user, mount,
  pid and network namespace, chroots into a tmpfs root, mounts the system
  read-only, mounts only the project writable, and drops the network to
  loopback. `self_test()` proves each of those four claims against the live
  kernel, and the sandboxed suite runs the same green result as an unsandboxed
  one.
- The frozen app uses a bundled interpreter for the namespace helper. Packaged
  self-development requires a successful boundary probe and fails closed when
  unavailable. In source mode, `auto` now **fails closed** (treated as
  `require`) unless `BABYMIND_ALLOW_UNSANDBOXED_AUTO=true` is set explicitly;
  never set that for untrusted code.
- **Ubuntu 24.04 and newer restrict unprivileged user namespaces** through
  AppArmor (`kernel.apparmor_restrict_unprivileged_userns=1`). On such hosts
  `sandbox.backend()` reports `none` and every sandboxed path - packaged
  self-edits, generated apps and the sandboxed test suite - fails closed.
  BabyMind does not change kernel settings for you; CI re-enables them with
  `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` on a
  disposable runner, and a desktop user who wants those features must decide
  that for their own machine.
- Memory is capped by RLIMIT_AS/RLIMIT_DATA (virtual address space/heap) and,
  when cgroup v2 delegation is available, an additional best-effort
  `memory.max` cgroup cap (reported as `CGROUP_MEM_SET`/`CGROUP_MEM_UNAVAILABLE`
  on stderr). Physical-RAM cgroup limits are not guaranteed on every kernel.
- **Nested sandboxes are detected but still single-layer.** Running BabyMind
  inside a container/VM is reported by `sandbox.status()` and
  `/api/broker/status` (`nested_sandbox_detected`), but user namespaces inside
  a user namespace add no second layer of isolation. Because of that, a handful
  of tests that need their own OS sandbox (generated-app execution and the app
  verifier) cannot run while the project's suite is itself executing inside
  BabyMind's sandbox. The packaged staging check therefore reports them as
  pre-existing problems - the same tolerance `apply_edits` applies - and only
  refuses a staged edit that regresses the suite, runs nothing, or is not
  sandboxed. Those tests still run normally in a source checkout and in CI.
- **Limits are rlimits, not cgroups.** CPU time, file size, open files, process
  count, and address space/heap (RLIMIT_AS + RLIMIT_DATA, 2 GiB by default,
  `BABYMIND_SANDBOX_MEM_BYTES`) are capped, and refused limits are reported as
  `LIMIT_FAILED`. Physical RAM is still not capped, because cgroup delegation
  is unavailable here; a runaway allocation is bounded by virtual-memory
  failure plus the parent's monitor and timeout, not by a cgroup memory cap.
- **Only the project root is writable, and that includes `state/`.** The sandbox
  protects your home directory, keys and the network, not the project's own
  files: a model-authored patch can still damage the checkout it is editing,
  which is what checkpoints and rollback are for.

## Autonomy

- **50 roles are 50 prompts over one model**, executed sequentially by default.
  There is no multi-model parallelism, no debate protocol beyond the shared
  digest, and no learned routing.
- A mission only edits source when started with `self_edit: true`. The frozen
  desktop edits a staged copy; it does not rebuild or activate those edits in the
  running application. The loop attempts a patch proposed by the Coding Agent,
  verified by compile and tests. After a failed
  verification it can request one repair and retry; malformed or unsafe proposals
  can stop the loop earlier. This is not an unrestricted iterative engineer.
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
  does not compile C#/Java/Rust/Go projects, produce packages for other
  operating systems or CPU architectures, or submit anything to an app store.
- Nothing is installed system-wide; generated apps run from their folder.
- Dependency installation for generated projects is not automated.

## Data and model

- No model is bundled in the repository. Installation downloads ~2.7 GB; the
  installer, download and checksum verification run automatically on every
  CI push and pull request on an Ubuntu 26.10 runner once one is registered, but
  other networks and a normal desktop session remain untested.
- The real-model acceptance job is permanent CI, not an opt-in dispatch, so a
  model that cannot answer its tested questions or emit a valid edit turns the
  build red. Its checks cover a fixed GUI question set, three source-mode chat
  questions, one coding task and two self-edits; they are not a measure of role
  competence or advice quality.
- Conversations, missions, and memory are encrypted at rest with a local key file on Linux. It is readable by the same user and does not protect against a compromised account.
- Knowledge-graph and voice integrations remain optional and unverified here.

## Interface

- The mission and self-development views were syntax-checked and served by the
  test server, but were not driven through a real browser in this environment.
- There is no diff viewer beyond the text `diff` field, no terminal emulator, and
  no project explorer tree in the UI yet (the API exposes `/api/dev/tree`).
