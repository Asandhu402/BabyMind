# BabyMind

BabyMind is a local-first AI development workspace for Linux, built around one assistant identity, one local language model, and 50 specialist role configurations.

## Product scope

**Linux is the only supported host platform.** Build scripts, runtime assumptions, CI, packaging, documentation, and release artifacts must target Linux. Do not add platform-specific compatibility layers for other desktop operating systems.

The 50 roles are specialist configurations over one shared model, not 50 independent models.

## Current capabilities

- Browser-based chat workspace and local conversation history.
- 50 specialist roles and mission orchestration.
- Local llama.cpp inference using a GGUF model.
- Optional encrypted local memory.
- Bounded public-web research.
- Task queue, approvals, audit trail, and checkpointed self-development.
- Linux namespace/chroot sandbox foundation, subject to kernel and host policy constraints.

Workspace file operations and general project command execution remain disabled until the Linux-native security broker and OS-enforced sandbox pass independent review and adversarial tests. A documentation or CI change does not count as implementation.

## Requirements

- 64-bit Linux.
- Python 3.10 or newer, including the distribution's Tk bindings for first-run model setup.
- A compatible local llama.cpp build providing `llama-server`.
- A compatible GGUF model.
- Node.js only for browser JavaScript checks in development CI.

Desktop-window integration through pywebview may require the GTK and WebKit2 system packages supplied by the chosen Linux distribution. The browser interface can also be opened directly in a local browser.

## Install from source

```bash
git clone https://github.com/Asandhu402/BabyMind.git
cd BabyMind
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

## Configure the local model

Set the absolute Linux paths to the llama.cpp server and your GGUF model:

```bash
export BABYMIND_ENGINE=llama.cpp
export BABYMIND_LLAMA_SERVER="$HOME/.local/bin/llama-server"
export BABYMIND_GGUF_MODEL="$HOME/.local/share/models/model.gguf"
export BABYMIND_CONTEXT_SIZE=4096
```

The server listens on `127.0.0.1:1235` by default. Optional settings include `BABYMIND_LLAMA_PORT`, `BABYMIND_TEMPERATURE`, `BABYMIND_TOP_P`, `BABYMIND_MAX_TOKENS`, and `BABYMIND_HOME`.

Start the web interface:

```bash
babymind-web
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

For an optional authenticated HTTPS session on a trusted private LAN:

```bash
babymind-web --lan
```

Keep LAN access opt-in. Do not expose the service directly to the public internet.

## Desktop window

Install the distribution's GTK and WebKit2 development/runtime dependencies required by pywebview, then run:

```bash
babymind-desktop
```

The desktop launcher and browser interface use the same local BabyMind server and data directory.

## Local data and encryption

BabyMind stores its local databases and key files under `~/.babymind` by default. Override this with `BABYMIND_HOME`. Encryption keys are separate owner-only files with mode `0600`; protect the account and device. Encryption at rest does not protect against malware running as the same user or access while BabyMind is unlocked.

Back up the complete BabyMind data directory securely. Losing a key file makes its corresponding encrypted data unrecoverable. Do not manually replace or delete key files.

## Development checks

```bash
python -m compileall -q src tests
node --check src/babymind/web/app.js
node --check src/babymind/web/approvals.js
python -m unittest discover -s tests -v
```

See [docs/PLATFORM_MISSION.md](docs/PLATFORM_MISSION.md), [docs/AUTONOMY_ROADMAP.md](docs/AUTONOMY_ROADMAP.md), and [SECURITY.md](SECURITY.md) for implementation gates and security boundaries.

BabyMind can make mistakes. Verify important results and inspect proposed code changes before using them.
