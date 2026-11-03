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

A passing automated test suite is not a security certification or penetration test.


## Local data encryption

BabyMind encrypts conversation titles, message bodies, and saved memory text with AES-256-GCM. On Windows, the 256-bit data key is protected using Windows DPAPI for the current user. The key files use the `.key` suffix beside their corresponding SQLite databases. Keep each key file with its database and do not delete it: losing the key makes encrypted content unrecoverable. This is at-rest protection, not protection against malware or an attacker operating as the unlocked Windows user. LAN mode uses TLS 1.2+ with a local certificate authority. Clients must explicitly trust the exported CA certificate. Use only on a trusted private Wi-Fi network.
