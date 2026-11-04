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
