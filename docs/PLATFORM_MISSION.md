# BabyMind platform mission: Linux only

**Effective immediately, BabyMind is a Linux-only product. Windows is not a supported, tested, packaged, or release target.** Do not add Windows compatibility or preserve Windows-specific product workflows as future requirements.

## Product scope

- Supported host operating system: Linux only.
- Primary target: 64-bit desktop Linux (x86_64). Keep architecture-specific assumptions explicit; add aarch64 only after CI and release validation exist.
- Support mainstream Linux distributions through documented prerequisites rather than distro-specific application forks. Ubuntu LTS and Fedora are the initial validation targets.
- Use Linux-native process, filesystem, permissions, key-storage, packaging, and sandboxing facilities.
- The application may expose a browser UI, but the BabyMind host/runtime must run on Linux.
- Windows and macOS desktop builds, installers, launchers, runtime packages, CI runners, and support instructions are out of scope.
- Do not describe the existing iPhone companion as a supported product target. A browser client may connect to a Linux-hosted instance over a trusted network, but no iOS app or iPhone-specific release is promised.

## Migration rules

1. Treat current Windows-specific code, documentation, scripts, artifacts, and workflows as legacy migration material, not evidence of support.
2. Replace Windows-specific paths, process handling, DPAPI key protection, WebView assumptions, launchers, build scripts, and packaging with Linux-native implementations.
3. Use a Linux desktop integration supported by the selected environment (Wayland/X11 as applicable); document GTK/WebKit or other runtime dependencies explicitly.
4. Protect local encryption keys with an available Linux Secret Service/libsecret provider where practical. Provide a carefully designed user-only-permission fallback (for example, mode 0600) only when its threat model and recovery implications are documented. Never silently reinterpret Windows-DPAPI key files as Linux keys.
5. Implement workspace access with Linux-native, descriptor-relative filesystem operations, symlink/mount boundary protections, race-resistant checks, and a narrow broker interface. Do not replace the Windows security design with superficial path-string checks.
6. Implement project execution only inside a real Linux OS-enforced sandbox with filesystem, network, process, and resource restrictions (for example, an appropriately configured bubblewrap, namespace, seccomp, cgroup, or equivalent design). Validate the exact guarantees before enabling execution.
7. Make Linux the only CI and release platform. Windows runners and Windows build/release jobs must be removed or replaced as part of migration; no green Windows job should be used as a release gate.
8. Add Linux tests for encryption, backups/restores, filesystem races, process lifecycle, local model startup, desktop launch, and package installation.
9. Preserve user data safely. Design and test an explicit migration/export path for existing Windows installations before removing legacy readers or formats. Never delete user data as part of a platform migration.
10. Keep the existing product invariants: one BabyMind identity, the 50 specialist role registry, local-first inference, explicit user control for consequential actions, auditable changes, and fail-closed security gates.

## Delivery phases

### Phase A — Linux baseline
- Inventory all Windows-specific code, docs, scripts, workflows, dependencies, release artifacts, and tests.
- Define the Linux support matrix, Python/runtime versions, desktop environment dependencies, data directories, and supported CPU/GPU acceleration.
- Establish Linux CI for unit tests, static checks, packaging, and a real local llama.cpp smoke test.

### Phase B — Linux-native application
- Port secure key storage, desktop launch, model setup, process management, filesystem paths, backup/restore, and diagnostics.
- Remove Windows-only launchers and packaging from the supported product.
- Update all user-facing instructions to Linux commands and paths.

### Phase C — secure autonomous development
- Complete the Linux-native workspace broker and independently review its security boundary.
- Complete adversarial symlink, mount, descriptor-replacement, race, permission, and concurrent-writer tests.
- Implement and validate a Linux OS-enforced execution sandbox before enabling project command/test execution.
- Keep file writes and consequential Git actions governed by clear approvals and audit logs.

### Phase D — Linux release acceptance
- Build and test the Linux distribution package(s) on Linux runners.
- Verify install, upgrade, rollback, model download/checksum, encrypted data persistence, backup/restore, and clean uninstall behavior.
- Publish Linux-only release artifacts and checksums.
- Remove obsolete Windows release workflows and clearly label any retained migration notes as historical and unsupported.

## Acceptance criteria

BabyMind is not considered Linux-ready merely because it starts on a Linux machine. Linux-only release acceptance requires:

- Linux is the sole documented and automated support target.
- No Windows runner, Windows package, Windows launcher, or Windows-specific release workflow remains active.
- All required app features have Linux implementations and automated Linux tests.
- Existing data/key compatibility and migration behavior are explicit and tested.
- The Linux workspace broker and execution sandbox pass independent security review before their respective capabilities are enabled.
- README, installation, troubleshooting, security, backup, and release documentation consistently describe Linux only.

**Current status:** This document changes the product mission and target platform. It does not itself complete the Linux port, remove all legacy Windows code, or establish Linux release readiness. Those require the phases and acceptance evidence above.
