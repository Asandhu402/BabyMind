# Security Policy

## Supported version

Security fixes are developed against the latest `main` branch. Please update to the latest release before reporting an issue.

## Reporting a vulnerability

Do not publish secrets, access tokens, private conversation data, or a working exploit in a public issue. Use GitHub's private vulnerability reporting feature for this repository when available. Include the affected commit, file or endpoint, impact, and safe reproduction steps.

## Safe-use notes

- Keep BabyMind bound to loopback unless LAN access is explicitly needed.
- LAN mode uses HTTPS with a local certificate authority and a bearer token. Install and explicitly trust the exported CA certificate on each client device. Use it only on a trusted private Wi-Fi network; do not expose the port to the internet.
- Conversation titles, message bodies, and saved memory text are encrypted at rest with AES-256-GCM. On Windows, the encryption key is protected with DPAPI for the current Windows user. Protect the Windows account and device; encryption does not protect against malware running as the same user or access while BabyMind is unlocked.
- The bundled local model and runtime should only be downloaded from the pinned sources documented in the repository.
- Every HTTP request must carry a `Host` header matching the address BabyMind was started on
  (`127.0.0.1`, `localhost`, `::1`, or the printed LAN IP). Requests addressed to any other host are
  rejected, which blocks DNS-rebinding pages from reading local conversations through the plain GET
  endpoints. Mutating requests additionally require a matching `Origin` or `Sec-Fetch-Site`.
- The local app builder is off unless `BABYMIND_APP_BUILDER_ENABLED=true`. When on, it writes only
  inside `<BABYMIND_BUILDER_ROOT>/apps/<slug>/`, never overwrites a file, requires the SHA-256 of the
  reviewed plan, and runs only the generated Python entry point (no shell). Generated code still
  runs with the current user's privileges and may use the network; it is not an OS sandbox.

## Autonomy, self-development, and command execution

- BabyMind can modify its own source only in a detected source checkout (or the
  folder in `BABYMIND_DEV_ROOT`). Every transaction is checkpointed first, then
  compiled and tested; a failing transaction is rolled back automatically and
  recorded in a hash-chained audit log at `state/dev-audit.jsonl`.
- Protected paths are never edited: `.git`, `state/`, encryption keys,
  databases, binaries, and model files.
- The execution runner is **not a sandbox**. It enforces an executable
  allowlist, a working-directory boundary, a scrubbed environment, output caps,
  a timeout, and process-tree termination. Same-user code still shares your
  files and your network. The API and CLI report `os_sandbox: false` rather than
  implying containment.
- `BABYMIND_RUNNER_UNRESTRICTED=true` removes the executable allowlist and is
  equivalent to giving the engine a shell. Leave it off unless you intend that.
- Mission contributions are written to an encrypted local SQLite database. They
  are model output, not verified facts; a mission can be wrong and still look
  authoritative. Read the recorded contributions before acting on them.
- BabyMind does not conceal actions: every apply, rollback, compile, and test run
  is appended to the audit log, and `babymind selfdev` reports chain integrity.

A passing automated test suite is not a security certification or penetration test.


## Local data encryption

BabyMind encrypts conversation titles, message bodies, and saved memory text with AES-256-GCM. On Windows, the 256-bit data key is protected using Windows DPAPI for the current user. The key files use the `.key` suffix beside their corresponding SQLite databases. Keep each key file with its database and do not delete it: losing the key makes encrypted content unrecoverable. This is at-rest protection, not protection against malware or an attacker operating as the unlocked Windows user. LAN mode uses TLS 1.2+ with a local certificate authority. Clients must explicitly trust the exported CA certificate. Use only on a trusted private Wi-Fi network.
