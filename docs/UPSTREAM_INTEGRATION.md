# Upstream integration: coding agent, native broker, and execution sandbox

**Status: integration foundation committed; runtime integrations remain disabled.**

This document maps the five selected upstream projects to BabyMind's architecture.
It is deliberately not a claim that their source code has been merged or that
their security guarantees have been inherited.

## Non-negotiable BabyMind constraints

- BabyMind remains the Windows application and the owner of its user experience.
- llama.cpp is the only model runtime. No LM Studio, hosted inference, cloud
  fallback, or provider credential is required.
- The model and agent planner are untrusted. The UI and Python server are also
  untrusted from the native broker's perspective.
- The broker owns authorization. The agent cannot approve its own requests.
- Project execution happens only inside an OS-enforced disposable sandbox.
- The host workspace is never modified by an autonomous agent before an exact
  patch has been reviewed and explicitly accepted.
- A failed security check means deny; there is no same-user subprocess fallback.

## Upstream component map

| Upstream | BabyMind responsibility | Integration decision |
|---|---|---|
| [OpenCode](https://github.com/anomalyco/opencode) | Coding-agent loop, project context, tool schemas, patch review and multi-step repair patterns | Reference the agent architecture; do not embed its full app or give it host tools |
| [Atomic Agent](https://github.com/AtomicBot-ai/atomic-agent) | Local llama.cpp agent loop, structured tool calls, durable sessions and approval patterns | Evaluate as the closest local-agent runtime reference; pin a release before any adapter |
| [wincage](https://github.com/rymorrisj/wincage) | Windows AppContainer and Job Object process-isolation primitives | Evaluate as a native sandbox primitive; not sufficient alone to claim production isolation |
| [sandbox-runtime](https://github.com/anthropics/sandbox-runtime) | Filesystem and network policy enforcement, restricted Windows identity | Evaluate as an independent sandbox implementation; upstream currently labels Windows support alpha |
| [OCBox](https://github.com/lucatirel/opencode-local-sandbox) | Disposable microVM, private Git clone, verified Git bundle handoff and host-integrity checks | Use as an end-to-end workflow reference; Docker Sandboxes must remain optional |

The five projects have different languages, process models, and security
boundaries. Copying all five repositories into BabyMind would duplicate entire
applications and create conflicting tool authorities. BabyMind instead owns
one typed integration boundary and adopts only reviewed components.

## Target architecture

1. **Coding intelligence:** BabyMind's llama.cpp provider supplies inference.
   The coding runtime builds a bounded project index, retrieves relevant files
   and symbols, plans a task, produces a unified diff, and evaluates test output.
   Tool calls are typed and schema-validated; source files, logs, and repository
   instructions are untrusted data.
2. **Native workspace broker:** a separate signed Windows process admits one
   user-selected workspace, pins its identity, grants only the minimum ACLs,
   displays its own approval UI, binds approval to the exact operation and
   content digest, and consumes that approval once. Python never performs
   privileged path resolution or file I/O.
3. **Execution sandbox:** a disposable restricted identity or microVM runs
   builds and tests with filesystem isolation, default-deny network egress,
   process/CPU/memory/time limits, bounded logs, cancellation, and guaranteed
   cleanup. The agent receives only a private clone or snapshot.
4. **Patch handoff:** sandbox output is exported as a verified Git bundle or
   patch. BabyMind verifies the base commit and working-tree state, displays
   the exact diff, and asks for explicit approval before applying it to the
   selected host workspace.
5. **Audit and recovery:** each action has a task ID, policy decision, bounded
   result, artifact digest, and timestamp. Checkpoints and rollback are
   required; push, merge, and release remain separate approvals.

## Integration order and acceptance gates

### Gate A — coding runtime
- Implement structured tool-call parsing and a bounded agent loop.
- Add repository inventory, ignore rules, language/framework detection, symbol
  and reference retrieval, context budgeting, and prompt-injection defenses.
- Generate unified diffs and verify they apply to the exact base snapshot.
- Add offline evaluations for bug fixing, feature implementation, refactoring,
  test generation, failing-test repair, and security review.
- Keep all workspace and command tools unavailable until Gate B and Gate C pass.

### Gate B — native broker
- Complete the existing C++ broker launcher, package verification, root identity
  pinning, workspace ACL grant/revoke, broker-owned approval UI, and one-use
  operation binding.
- Evaluate wincage's AppContainer/Job Object primitives without treating them
  as a substitute for BabyMind's own authorization protocol.
- Add adversarial tests for traversal, reparse points, TOCTOU, stale/replayed
  approvals, forged IPC, process escape, ACL cleanup, and crash recovery.
- Obtain an independent Windows security review before enabling file actions.

### Gate C — execution sandbox
- Compare wincage with sandbox-runtime's Windows restricted-identity/WFP design.
- Evaluate OCBox's microVM and verified Git handoff as the stronger isolation
  option when Docker Sandboxes are available.
- Do not combine overlapping sandbox managers in one process. Select one
  backend only after threat-model and compatibility testing.
- Test that private files, credentials, host services, LAN endpoints, and
  network egress are inaccessible unless explicitly allowlisted.
- Verify resource limits, process-tree termination, cleanup, and fail-closed
  behavior on Windows 11 Home and the packaged runtime.

### Gate D — integrated workflow
- Connect the coding runtime to broker-mediated read and patch operations.
- Run commands only in the approved sandbox, never in the BabyMind server's
  security context.
- Verify the sandbox's Git bundle against the original base and keep the host
  worktree unchanged until user approval.
- Add pause, resume, cancel, checkpoint, rollback, and audit history.

### Gate E — Windows release
- Run end-to-end tasks against clean sample repositories and a real BabyMind
  checkout using only the pinned local llama.cpp model.
- Test offline startup, first-run model verification, restart/recovery,
  cancellation, rollback, and resource exhaustion.
- Publish limitations, checksums, dependency notices, and test evidence.
- Do not mark release-ready or merge the integrated release until all gates pass.

## Current safety state

BabyMind's existing `WORKSPACE_FILE_ACTIONS_ENABLED = False` guard must remain
false. The native broker currently has experimental handle-relative filesystem
primitives and an AppContainer smoke launcher, but its production authorization
path and ACL lifecycle are incomplete. The coding assistant is drafting-only.
Project execution is disabled. The new upstream registry is descriptive only
and does not load or launch any third-party component.

## Upstream references

- [OpenCode](https://github.com/anomalyco/opencode)
- [Atomic Agent](https://github.com/AtomicBot-ai/atomic-agent)
- [wincage](https://github.com/rymorrisj/wincage)
- [Anthropic sandbox-runtime](https://github.com/anthropics/sandbox-runtime)
- [OCBox](https://github.com/lucatirel/opencode-local-sandbox)


---

# Pinned upstream source integrations

BabyMind tracks the five selected upstream codebases as Git submodules. Each submodule is pinned to an immutable commit in the parent repository; updating an upstream requires a reviewed pointer change and compatibility/security checks.

## Pinned sources

| Component | Local path | Upstream | Pinned commit | License |
|---|---|---|---|---|
| OpenCode | `vendor/upstream/opencode` | https://github.com/anomalyco/opencode | `8568952e77be2137289d12ecf264bdfca7809578` | MIT |
| Atomic Agent | `vendor/upstream/atomic-agent` | https://github.com/AtomicBot-ai/atomic-agent | `fdc7813cb1b2d7a72781c957b211e03af5e02130` | MIT |
| wincage | `vendor/upstream/wincage` | https://github.com/rymorrisj/wincage | `6f76360cab2d4ba503554474f264dc69932ed781` | MIT |
| Anthropic Sandbox Runtime | `vendor/upstream/sandbox-runtime` | https://github.com/anthropics/sandbox-runtime | `98a4016d27609ed34dd1fb43d23ed6efb6eeeb77` | Apache-2.0 |
| OCBox | `vendor/upstream/ocbox` | https://github.com/lucatirel/opencode-local-sandbox | `b9d1e1939e08541a368859d0de7752c800ac63de` | MIT |

These are source checkouts, not Python runtime dependencies. Their own license and notice files remain in each submodule. Review dependency licenses and notices again before redistributing a packaged BabyMind build.

## Clone and update

Clone the integrated source tree with:

```powershell
git clone --recurse-submodules https://github.com/Asandhu402/BabyMind.git
```

For an existing checkout:

```powershell
git submodule update --init --recursive
```

Do not use floating upstream branches in a release. Update a submodule pointer only after reviewing the exact upstream diff, license changes, build requirements, Windows compatibility, and security impact.

## Intended component boundaries

- **Agent runtime candidates:** OpenCode and Atomic Agent. These overlap; they are not both started as independent autonomous agents by default. BabyMind's native UI/provider/session layer remains the controller, and llama.cpp remains the only model backend.
- **Windows process isolation candidate:** wincage (AppContainer / Job Object-oriented controls). Treat its grants, token behavior, and process-tree coverage as security-sensitive and independently test them.
- **Cross-platform sandbox candidate:** Anthropic Sandbox Runtime. Its Windows implementation uses a dedicated local account and Windows Filtering Platform controls. It is a separate backend candidate, not an automatic fallback.
- **Disposable microVM workflow:** OCBox. It wraps OpenCode with Docker Sandboxes, a private Git clone, and verified Git-bundle handoff. It overlaps with the OpenCode runtime and has additional Docker / virtualization prerequisites.

## Runtime and security status

Adding these repositories as pinned submodules makes their source available to developers. It does **not** mean BabyMind currently builds, launches, trusts, or exposes their functionality.

No upstream agent or sandbox is enabled by this change. Do not execute upstream install scripts automatically. Do not enable workspace writes or project execution as a side effect of initializing submodules.

Before enabling a backend, BabyMind must provide a narrow adapter with explicit capability declarations, signed/hash-verified binaries, user-visible approval bound to the exact operation, deny-by-default filesystem/network policy, bounded resources, cleanup, audit logging, and adversarial Windows tests. There must be no unsandboxed host fallback.

The current Python project does not automatically build or install these Node/TypeScript, Python, or Docker-based projects. In particular, Atomic Agent currently declares Node.js >=25.7.0; OpenCode uses Bun; OCBox requires Docker Sandboxes and Windows virtualization. These toolchains must be isolated from the ordinary BabyMind install and validated separately.

## Model policy

BabyMind supports llama.cpp only. Do not add LM Studio or mandatory cloud inference while adapting these projects. Configure each adapter to use the user's local llama.cpp endpoint and validate model/API compatibility before launch.
