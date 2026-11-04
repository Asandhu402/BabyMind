# BabyMind

BabyMind is a local-first AI workspace for **Linux x86-64** with a desktop
window and a bundled CPU llama.cpp runtime. Its 50 specialist roles are prompts
over one model, not independent people or independently trained agents.

## Install on Ubuntu with one command

On Ubuntu 22.04 or newer, x86-64, open a terminal as your normal user and run:

```bash
sudo apt-get update && sudo apt-get install -y git ca-certificates && bash -c 'set -e; d=$(mktemp -d); trap "rm -rf -- \"$d\"" EXIT; git clone --depth 1 https://github.com/Asandhu402/BabyMind.git "$d/repo"; bash "$d/repo/install-linux.sh"'
```

This command downloads and executes the current repository's installer. Review
`install-linux.sh` and its dependencies before running it. It uses `sudo` to
install Ubuntu packages, downloads about 2.71 GB of model weights, verifies the
pinned model SHA-256, builds the CPU runtime and desktop, and creates a BabyMind
application-menu entry. It requires a working internet connection, time to
compile, a graphical desktop, and ample disk space (at least 4.5 GB for the
model plus several GB for dependencies and build files; 10 GB free recommended).
It may prompt for your sudo password. Open **BabyMind** from Applications when
finished, or run `~/.local/bin/babymind`.

The single-command installer has **not been validated end to end** on a clean
Ubuntu desktop or against the real model host in this environment. The merged
Linux CI passed its Qt GUI fixture, but that is not a real desktop installation
or production-model test; see [verification](docs/LINUX_VERIFICATION.md).

## Portable desktop

The target is a graphical Linux desktop with glibc 2.35 or newer (for example
Ubuntu 22.04+) and standard Qt WebEngine system libraries. Extract the complete
Linux portable archive and run `./BabyMind` (or open the executable in your file
manager). On first launch BabyMind asks to download a roughly 2.71 GB model,
verifies its SHA-256, and saves it under `~/.babymind/models`. The download
requires internet and at least 4.5 GB free. Subsequent launches use the local
model. There is no API key, paid service, LM Studio or auto-updater.
CPU inference may be slow and needs substantial memory.

The Linux package and first-run GUI have **not yet been validated end to end**
in this environment. See [Linux portable instructions](docs/LINUX_PORTABLE.md)
for compatibility, building from source, and current limitations. Linux is the sole supported desktop target.

## Safety and capabilities

- Chat, history, local memory, advisory development review, mission control,
  read-only GitHub research, and optional integrations exist. A review is model
  output, not independent verification; the autonomous development platform is
  not complete. See [autonomous platform audit](docs/AUTONOMOUS_PLATFORM_AUDIT.md).
- Desktop command execution defaults to `BABYMIND_SANDBOX=require`, which
  refuses execution because the Python-based namespace launcher is unavailable
  in the frozen app. The source runner's
  `auto` mode can fall back to unsandboxed execution; do not use it for untrusted
  code. The portable executable is not a Python interpreter: source test runs
  generated Python execution, and self-development edits are unavailable in the
  portable app.
- Data is in `~/.babymind` (or `BABYMIND_HOME`). Conversation and memory text
  are encrypted, but on Linux the key is a local file readable by your user;
  protect the account and back up databases **and** keys. Encryption is not a
  defence against malware running as the same user.
- Downloads, third-party dependencies and the model have their own licenses;
  assess them before redistribution. This repository currently has no top-level
  license file. No license to redistribute the project is implied.

See [security policy](SECURITY.md) and [known limitations](docs/KNOWN_LIMITATIONS.md).
