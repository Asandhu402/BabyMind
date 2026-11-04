# Upstream integration: coding agent, workspace broker, and execution sandbox

**Status: integration foundation only; runtime integrations remain disabled until their security and compatibility gates pass.**

This document records architecture references. It does not claim upstream code has been merged or that external security guarantees have been inherited.

## Non-negotiable BabyMind constraints

- BabyMind owns one user experience and one assistant identity.
- llama.cpp is the only model runtime.
- The model, planner, UI, and Python server are untrusted from the workspace broker's perspective.
- The broker owns authorization. An agent cannot approve its own requests.
- Project execution happens only inside a Linux OS-enforced disposable sandbox.
- The host workspace is never modified by an autonomous agent before an exact patch has been reviewed and accepted.
- A failed security check means deny; there is no unrestricted subprocess fallback.

## Upstream component map

| Upstream | Potential value | Integration decision |
|---|---|---|
| [OpenCode](https://github.com/anomalyco/opencode) | Coding-agent loop, project context, tool schemas, patch review and repair patterns | Reference architecture; do not embed its full application or grant host tools |
| [Atomic Agent](https://github.com/AtomicBot-ai/atomic-agent) | Local agent loop, structured tool calls, durable sessions and approval patterns | Evaluate as a local-agent runtime reference; pin and audit before any adapter |
| [sandbox-runtime](https://github.com/anthropics/sandbox-runtime) | Filesystem and network policy enforcement | Evaluate its Linux capabilities and threat model independently before adoption |
| [OCBox](https://github.com/lucatirel/opencode-local-sandbox) | Disposable microVM, private Git clone, verified Git bundle handoff and host-integrity checks | Use as an end-to-end workflow reference; external virtualization remains optional |

These projects have different languages, process models, and security boundaries. Copying entire repositories into BabyMind would duplicate applications and create conflicting tool authorities. BabyMind owns one typed integration boundary and adopts only reviewed components.

## Target architecture

1. **Coding intelligence:** llama.cpp supplies inference. The coding runtime builds a bounded project index, retrieves relevant files and symbols, plans tasks, produces unified diffs, and evaluates test output. Tool calls are typed and schema-validated; source files and logs are untrusted data.
2. **Linux workspace broker:** a narrow Linux-native broker admits one user-selected workspace, pins its directory identity, enforces descriptor-relative operations, displays exact approvals, and consumes each approval once. Python does not perform broker-authorized path resolution or file I/O.
3. **Execution sandbox:** a disposable Linux isolation boundary runs builds and tests with explicit filesystem, network, process, and resource limits. It returns bounded logs and test results, not ambient host access.
4. **Patch handoff:** a verified diff is returned to BabyMind. The user reviews the exact change before it is applied to the host workspace.
5. **Audit and recovery:** record tool inputs, approvals, hashes, exit status, and rollback checkpoints without storing secrets or unnecessary file contents.

## Integration gates

- Confirm the exact upstream license and pinned revision.
- Review the dependency tree and update cadence.
- Verify local llama.cpp connectivity without cloud fallback.
- Test path traversal, symlink and mount escapes, concurrent replacement, process termination, resource exhaustion, and network isolation.
- Keep every adapter disabled until its integration tests and independent security review pass.
- Never import a third-party tool's permission model as BabyMind authorization.

## Release acceptance

The coding assistant may draft code before the broker is complete, but workspace reads, writes, and project execution remain disabled until the relevant Linux security gates pass. Do not claim production sandboxing from namespaces, containers, or path validation alone.
