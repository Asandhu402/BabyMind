# BabyMind platform mission: Linux only

**BabyMind is a Linux-only product.** The host application, runtime, build, CI, packaging, documentation, and release artifacts must target Linux exclusively.

## Product scope

- Supported host: 64-bit Linux desktop (x86_64).
- Initial validation distributions: Ubuntu LTS and Fedora. Add further distributions or architectures only after CI and release validation.
- Use Linux-native process, filesystem, permissions, key-storage, desktop integration, packaging, and sandboxing facilities.
- The application may expose a browser interface to other devices on a trusted private network; the BabyMind host and local model run on Linux.
- The iPhone companion is not a separate product target.

## Migration rules

1. Remove legacy platform-specific source, documentation, scripts, artifacts, workflows, and package assumptions.
2. Use Linux-native paths, process handling, launchers, and desktop integration. Document GTK/WebKit dependencies for pywebview.
3. Store encryption keys in a Linux Secret Service provider where practical; otherwise use a carefully documented owner-only file fallback with mode 0600. Never silently reinterpret an unsupported legacy key format.
4. Implement workspace access with Linux-native descriptor-relative filesystem operations, symlink/mount boundary protections, race-resistant checks, and a narrow broker interface.
5. Implement project execution only inside a real Linux OS-enforced sandbox with filesystem, network, process, and resource restrictions. Validate the exact guarantees before enabling execution.
6. Run CI and releases on Linux only.
7. Add Linux tests for encryption, backup/restore, filesystem races, process lifecycle, local model startup, desktop launch, and package installation.
8. Preserve user data. Keep encrypted database files and key files intact during migration; provide explicit export/restore guidance where old formats cannot be opened.
9. Keep the product invariants: one BabyMind identity, 50 specialist role configurations, local-first inference, user control for consequential actions, auditable changes, and fail-closed security gates.

## Delivery phases

### Phase A — Linux baseline
- Establish Ubuntu LTS and Fedora CI.
- Remove stale platform-specific launchers, native code, scripts, and release workflows.
- Verify Python dependencies, browser assets, CLI, and local llama.cpp startup.

### Phase B — Linux-native application
- Validate the desktop window and browser interface on both initial distributions.
- Complete local key storage, backup/restore, permissions, and data-home behavior.
- Provide clear install, update, uninstall, and recovery instructions.

### Phase C — secure autonomous development
- Implement and independently review the Linux workspace broker.
- Implement and adversarially test OS-enforced project execution.
- Connect coding-agent file operations only after broker and approval gates pass.
- Preserve checkpoints, rollback, and tamper-evident audit history.

### Phase D — Linux release acceptance
- Build and test on clean Linux environments.
- Verify model download integrity, startup, inference, data persistence, backups, and uninstall.
- Publish Linux source distributions and supported packages with checksums.
- Document known limitations accurately.

## Release acceptance

A Linux-only release is not complete until:
- CI passes on the declared Linux distribution matrix.
- No unsupported-platform source, scripts, documentation, workflows, or package artifacts remain.
- Desktop and browser launch paths work on the declared distributions.
- Local model startup and real inference are tested.
- Encryption, backup, restore, and key permissions are tested.
- Workspace writes and project execution remain disabled unless their security reviews and adversarial tests pass.
- The README describes only verified capabilities.
