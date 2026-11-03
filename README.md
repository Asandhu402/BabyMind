# BabyMind

BabyMind is a local-first personal AI application with exactly **50 specialist roles**, one consistent assistant identity, a browser-based interface, optional shared memory, and selectable local model backends (LM Studio or llama.cpp).

The 50 agents are specialist configurations that share one underlying language model. They are not 50 separately trained or separately running models. The optional collaboration mode performs a specialist pass, a quality-review pass, and a final synthesis pass using that same model.

## What is included

- **Chat workspace:** responsive browser UI, conversation history, agent selector, typing indicator, prompt starters, dark/light themes, and Markdown conversation export.
- **Local text attachments:** attach small TXT, Markdown, CSV, JSON, source-code, or config files (up to 12 KB) for model context.
- **50-agent directory:** searchable and filterable BM-01 through BM-50 role catalogue, each with a focused domain playbook and responsibility.
- **Unified coordinator:** one BabyMind identity with role-specific instructions.
- **Collaboration mode:** selected specialist, QualityReviewer (BM-49), then Coordinator (BM-01).
- **Encrypted local memory:** opt-in SQLite task/response memories, encrypted at rest with AES-256-GCM; the encryption key is protected by Windows DPAPI on Windows. When enabled, BabyMind ranks relevant notes locally using lightweight text matching; no embeddings or extra AI model are used. The Memory workspace also supports local search.
- **Encrypted conversation storage:** local SQLite history on the computer running BabyMind; message text and titles are encrypted at rest with AES-256-GCM.
- **Local model adapters:** LM Studio's OpenAI-compatible API or a BabyMind-managed llama.cpp server using a local GGUF model.
- **CLI:** health, list, ask, route, and memory commands.
- **Lightweight runtime:** core server, storage, and HTTP client use the Python standard library; the desktop window uses pywebview.

## Requirements

For running from source: Windows 10/11 and Python 3.10 or newer, plus either LM Studio or a compatible llama.cpp runtime and local model. The portable Windows desktop package bundles Python and the llama.cpp CPU runtime; it downloads and verifies its default GGUF model on first launch. A current Microsoft Edge WebView2 Runtime is required for the desktop window.

## Install

Open PowerShell in the repository folder:

    py -m pip install -e .

## Start the model

1. Open LM Studio and download a model that fits the computer's available memory.
2. Load the model.
3. Start the local server in LM Studio.
4. Keep the default endpoint at `http://127.0.0.1:1234/v1`, unless you configure another one.

Optional environment variables:

- `BABYMIND_BASE_URL` — local OpenAI-compatible endpoint; defaults to `http://127.0.0.1:1234/v1`
- `BABYMIND_MODEL` — optional explicit model ID; otherwise BabyMind discovers the first loaded model
- `BABYMIND_API_KEY` — optional key if the local server requires one
- `BABYMIND_HOME` — optional location for BabyMind's SQLite data


## Choose BabyMind's local model engine

BabyMind can use LM Studio, or launch its own local `llama.cpp` server. The
portable Windows desktop package bundles the CPU runtime and offers a verified
first-run model download. For source/developer launches, you still provide the
runtime and GGUF model paths yourself. Both modes run inference on this computer.

### llama.cpp setup on Windows

1. Download the official Windows **x64 CPU** release from
   [ggml-org/llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases).
   Extract it to a folder such as `C:\BabyMind\llama.cpp\`.
2. Obtain a compatible `.gguf` model and save it in a folder such as
   `C:\BabyMind\models\`.
3. In PowerShell, set the paths for your current terminal session:

       $env:BABYMIND_ENGINE = "llama.cpp"
       $env:BABYMIND_LLAMA_SERVER = "C:\BabyMind\llama.cpp\llama-server.exe"
       $env:BABYMIND_GGUF_MODEL = "C:\BabyMind\models\your-model.gguf"

4. Start BabyMind with `babymind-desktop` or double-click the desktop launcher
   after setting these variables in Windows Environment Variables.

BabyMind starts `llama-server.exe` on `127.0.0.1:1235`, waits for the model
to load, sends chat requests to its local OpenAI-compatible API, and stops the
server process it started when BabyMind exits. The default context size is
4096 tokens; override it with `BABYMIND_CONTEXT_SIZE`. Set
`BABYMIND_LLAMA_PORT` to change the local port. This initial engine mode uses
the CPU build by default; acceleration depends on the llama.cpp build you
download and its compatible runtime libraries.

### Switch back to LM Studio

For source/developer launches, set `BABYMIND_ENGINE=lm-studio` to use LM Studio.
The portable Windows package uses its bundled llama.cpp engine by default.
You can also set `BABYMIND_BASE_URL`, `BABYMIND_MODEL`, and `BABYMIND_API_KEY`
for compatible local servers.

## Start the BabyMind interface

    babymind-web

Then open [http://127.0.0.1:8765](http://127.0.0.1:8765).

On Windows, you can double-click `Start-BabyMind.bat` to install and launch the local app. For iPhone access on the same trusted Wi-Fi network, double-click `Start-BabyMind-iPhone.bat` or run:

    babymind-web --lan

The terminal prints an HTTPS address, a one-time access token, and the public local CA certificate path. Before opening the address on your iPhone, transfer the `lan-ca.crt` certificate to the iPhone (for example with AirDrop), install the certificate profile, then enable full trust under **Settings > General > About > Certificate Trust Settings**. Open the printed HTTPS address in Safari and enter the token. The certificate's private key stays on the computer and is encrypted at rest. Use only on a trusted private Wi-Fi network; this is not intended for public internet exposure.


## Windows desktop application

### Portable Windows desktop package

The GitHub Actions workflow builds a portable Windows package containing
BabyMind, its Python runtime, and the official llama.cpp Windows CPU runtime.
Download the complete `BabyMind-Windows-Portable` artifact from the latest
successful Windows build, extract it, and double-click `BabyMind.exe`.

On first launch, BabyMind asks permission to download the Qwen3.5-4B
Uncensored HauhauCS Aggressive Q4_K_M fine-tune (approximately 2.71 GB).
It displays download progress, verifies the file against the SHA-256 checksum
published in the Hugging Face file metadata, and stores the model
under `%USERPROFILE%\.babymind\models`. Later launches reuse that model
locally; the download is not repeated. The first download requires internet
access and at least 4.5 GB of free disk space.

### iPhone companion included in the portable package

The portable ZIP also includes `BabyMind-iPhone.exe` and
`Start-BabyMind-iPhone.bat`. Choose one launcher at a time: close
`BabyMind.exe` before starting the iPhone companion, and close the companion
before reopening the desktop app. Each launcher runs its own local model
server, while both reuse the same verified model file and data folder. If the
model is not already installed, the first launch downloads it (about 2.71 GB),
so keep the PC online and allow at least 4.5 GB of free disk space.

1. Extract the **entire** ZIP to a normal folder (not inside the ZIP).
2. Connect the iPhone and Windows PC to the same trusted private Wi-Fi network.
   Avoid guest Wi-Fi or networks that isolate connected devices.
3. Double-click `Start-BabyMind-iPhone.bat`. If Windows Firewall asks, allow
   access on **Private networks only**; never enable Public network access.
4. Keep the Windows console open and prevent the PC from sleeping. It prints
   the HTTPS address, a fresh one-time access token, and the path to the public
   `lan-ca.crt` certificate.
5. Transfer **only** `lan-ca.crt` to the iPhone (for example with AirDrop).
   Do not transfer any private-key file. Install the certificate profile, then
   enable full trust under **Settings → General → About → Certificate Trust
   Settings**.
6. Open the exact HTTPS address printed by BabyMind in iPhone Safari. Enter the
   one-time token when prompted. Keep the token private.

The companion uses the same local model, encrypted data directory, and
token-protected HTTPS server as BabyMind. In LAN mode it binds to the detected
local network address rather than every network interface. It does not create
a cloud account or intentionally expose the service to the public internet.
Do not configure router port forwarding. The certificate authority is generated locally and
its private key stays on the PC. The public CA certificate normally remains
the same between starts on this Windows installation; the server certificate
is renewed when the companion starts. A fresh access token is generated on
every server start.

**Recovery and common issues**

- If Safari cannot connect, confirm both devices are on the same non-guest
  Wi-Fi, the PC is awake, the console is still running, and Windows Firewall
  permits BabyMind on Private networks.
- If the saved token stops working after restarting the companion, reload the
  page and enter the new token printed in the console.
- If port 8765 is already in use, run
  `BabyMind-iPhone.exe --port 8766` from PowerShell in the extracted folder,
  then use the new address printed by the app.
- If iOS reports an untrusted certificate, check that the installed
  `lan-ca.crt` profile is enabled under Certificate Trust Settings. Only
  install the certificate you transferred directly from your own PC.
- To stop LAN access, close the companion console. No router rule or cloud
  service should be left running.

**Model and data recovery**

- If the first model download is interrupted, close BabyMind and start either
  launcher again. An incomplete download is discarded; setup can be retried.
  BabyMind checks the model's SHA-256 on startup and will replace a damaged
  model with a fresh download.
- Conversations and the default encrypted memory stay in
  `%USERPROFILE%\\.babymind` on the Windows PC. The iPhone is a browser
  companion; the PC must remain on and awake while you use it.
- To back up, open BabyMind **Settings → Backup**, choose a destination on the
  PC outside the live `.babymind` folder, and use a strong password of at
  least 12 characters. Store the backup and password separately.
- Restore replaces the current BabyMind data, requires typing
  `RESTORE BABYMIND`, and should only be done after making a backup of the
  current data. Restart BabyMind after a restore.
- Important Windows limitation: the backup is password-encrypted, but the
  database encryption keys are also protected by Windows DPAPI. Restore is
  supported only under the **same Windows user account on the same PC**; this
  backup is not a migration method to a different computer or Windows account.
- The backup contains BabyMind's encrypted databases and their key files; it
  does not include the downloaded AI model or the LAN certificate. After a
  fresh install, the model can be downloaded again. If the `.babymind/certs`
  folder is lost or recreated, transfer the new `lan-ca.crt` to the iPhone
  and repeat the iOS certificate-trust step.

This feature still needs a real iPhone/Windows device test before it can be
described as fully verified.

A permanent, versioned Windows release is published by the **BabyMind
Windows release** workflow. Run it from GitHub Actions with a tag matching
`pyproject.toml` (currently `v0.3.0`), or push that tag. The workflow repeats
the Windows tests and build, then attaches a versioned ZIP and SHA-256 checksum
to the GitHub Release. The package is portable but currently unsigned.

The packaged desktop app selects its bundled llama.cpp engine automatically
and does not require LM Studio, Python, or an API key. Inference and chat
storage remain on the user's computer. The desktop window requires Microsoft
Edge WebView2 Runtime, which is normally present on current Windows 11 systems.
If WebView2 is missing, install Microsoft's official Evergreen Runtime.

For developers building from source, install Python 3.10 or newer and run:

    .\build-windows.ps1

The output is `dist\BabyMind\BabyMind.exe`; copy the entire
`dist\BabyMind` folder, not just the EXE. The build is not code-signed and
is not a traditional installer yet. The packaged default is the community
fine-tuned Qwen3.5-4B Uncensored HauhauCS Aggressive Q4_K_M model, pinned to a
specific Hugging Face revision and verified against its published SHA-256
checksum. It is a third-party fine-tune, not an official Alibaba release.
Its publisher describes it as aggressively uncensored; actual behaviour and
quality must still be tested.

## Use the command line

    babymind health
    babymind list
    babymind run BM-01 "Route this task without calling a model"
    babymind ask BM-02 "Research this question using the local model"
    babymind ask BM-01 "Remember this preference" --remember
    babymind ask BM-02 "Use relevant context from before" --use-memory
    babymind memory list
    babymind memory clear

- `run` checks role routing and does not call a model.
- `ask` sends the request to the selected local model engine with the selected role instructions.
- Memory is opt-in. Use `--remember` to save and `--use-memory` to include relevant recent notes.
- In the web UI, the **Remember** and **Use memory** controls are separate.

## Developer checks

Run the automated test suite from the repository root:

    py -m unittest discover -s tests

## Privacy and data

- The default web server listens only on `127.0.0.1`.
- Conversations and memory are stored under `~/.babymind/` by default (or `BABYMIND_HOME`). Message text, conversation titles, and saved memory content are encrypted at rest with AES-256-GCM. On Windows, the encryption key is protected by Windows DPAPI for the current Windows user; do not delete or move the `.key` files independently of their databases.
- Memory is not automatically written unless the user enables **Remember** for that request.
- Encryption protects stored text when BabyMind is closed. It does not protect data while the app is running, from malware running as the same Windows user, or from someone who can unlock that Windows account.
- No analytics, account service, or cloud model is included in the application.
- The model runner is local; the model's own behavior and resource requirements depend on the selected model and runtime.

## Public web research (opt-in)

The chat composer includes a **Web research** toggle. When enabled, BabyMind
sends the current question to DuckDuckGo's public HTML search endpoint and
passes up to five result titles, URLs, and short snippets to the same local
model for synthesis. An additional **Read source pages** toggle optionally
fetches the first two results as plain text. Page reading is limited to public
HTTP(S) hosts on standard ports, blocks private/local/reserved addresses and
unsafe redirects, accepts HTML/plain text only, caps each response at 1 MB and
12 seconds, and passes at most 5,000 characters per page into the prompt.
Scripts are never executed. Search queries and requested public pages leave
the computer; model inference and conversation storage remain local. Search
snippets and page text are unverified third-party content. Review original
sources before relying on claims.

The search API is `POST /api/research` with JSON
`{"query":"your research question","limit":5}`; the limit is 1–10 and query
length is capped at 500 characters. The optional page API is
`POST /api/research/page` with JSON `{"url":"https://example.com/article"}`.
Both endpoints remain subject to local/LAN authorization and origin checks.


## Current capability boundaries

The 50 entries are not independent AI brains: they are 50 focused roles routed to one shared model. Collaboration mode is a sequential multi-pass workflow, not 50 agents reasoning simultaneously. Document analysis and speech transcription are routed through the core coordinator when their optional packages are installed. Browser automation is available only as an explicitly approved, supervised local-browser task behind a disabled-by-default environment gate. Open Interpreter can be launched in workspace-write mode for one explicitly selected project folder: it can edit project files and run project commands, while network access is disabled and requests beyond the workspace require approval. Its native Windows sandbox must enforce the boundary and fail closed if unavailable; this is not full-PC access. The packaged model is an aggressively uncensored community fine-tune, but no
model can guarantee unrestricted behaviour on every prompt. iPhone use is supported on a trusted local Wi-Fi network with a one-time access token.

## Fixed invariant

BabyMind validates that the canonical registry contains exactly 50 unique, sequential IDs from BM-01 through BM-50.

**Security status:** The coding assistant supports OS-sandboxed workspace-write sessions for a selected project, with on-request escalation approvals and network disabled. BabyMind's separate in-app workspace file broker remains disabled pending native race-resistant filesystem protections.


## Installation diagnostics

Run the non-destructive diagnostic command from PowerShell:

    babymind doctor

It checks the Python version, 50-role registry, local storage permissions,
existing encrypted memory database/key availability, local model connection,
and the current workspace/execution security gates. It never starts a model,
executes project code, or creates a replacement encryption key. A disconnected
model is reported as a warning so you can start LM Studio and run the command
again. A missing memory key is a failure: do not delete or replace it.


## Encrypted backup and restore

Open **Settings → Encrypted backup** to create a password-protected `.bmbak`
file or restore one. BabyMind snapshots its encrypted conversation/task
database and encrypted memory database without exporting plaintext chat or
memory. The archive is authenticated with AES-256-GCM and a key derived from
your backup password using scrypt. Use a strong password of at least 12
characters and keep it separately; BabyMind cannot recover a forgotten
password.

On Windows, the database encryption keys are protected by DPAPI and remain
bound to the same Windows user on the same computer. This backup is intended
for disaster recovery on that installation, not migration to another device
or Windows account. Restoring replaces the current local databases, requires
typing `RESTORE BABYMIND`, validates the archive, database integrity and
encryption keys before replacing files, and should be followed by restarting
BabyMind. Keep a separate copy of the backup outside `~/.babymind/`.

## Integrated capabilities

Open **Settings → Connected tools** in BabyMind. These are product capabilities routed through the same BabyMind coordinator, identity, local model and encrypted conversation history; they are not separate assistants.

- **Document understanding:** Docling extracts local documents and sends their content to the shared coordinator.
- **Speech:** faster-whisper and Voicebox transcription feed the same coordinator; Voicebox speech output uses the same BabyMind identity.
- **Knowledge retrieval:** Cognee search is answered by the shared coordinator and can use BabyMind's encrypted memory. Only individually approved notes are indexed. Cognee's separate graph/vector store is not encrypted by BabyMind, so do not index secrets.
- **Browser automation:** supervised local browser tasks require explicit approval before launch.
- **Coding:** Open Interpreter runs against the local model with workspace-write access confined by the OS sandbox to the selected project folder. Network access is disabled and escalation requires approval. If the OS sandbox cannot be enforced, the session must fail closed. This is not full-PC access.
- **Quality and security:** Promptfoo is part of the repository's developer/CI quality workflow and tests BabyMind through its loopback API; it is not another runtime assistant.

Some capabilities need their local engine installed or running because large speech/document models and browser runtimes should not be forced into every lightweight install. They are still integrated BabyMind capabilities, not separate AI products. Install or start only the local engine needed by a capability:

    py -m pip install -e ".[documents]"
    py -m pip install -e ".[voice]"
    py -m pip install -e ".[browser]"
    py -m pip install -e ".[knowledge-graph]"

Voicebox runs as a loopback-only local service. Cognee requires explicit per-note approval and a separate local storage review. See [capability setup and safety](docs/OPTIONAL_INTEGRATIONS.md) and [quality checks](quality/README.md).

Check engine availability without starting models:

    babymind integrations

## Additional optional local integrations

BabyMind can connect to three additional open-source projects without creating new assistant identities:

- **Cognee** adds an opt-in local knowledge graph. Only individually approved notes are indexed; BabyMind never copies all encrypted conversation history. Cognee's separate local graph/vector files are not encrypted by BabyMind. Install with `py -m pip install -e ".[knowledge-graph]"` and set `BABYMIND_COGNEE_ENABLED=true` after reviewing the privacy warning.
- **Voicebox** adds local speech output and an alternative speech-to-text server. Run its Docker service on 127.0.0.1:8790; CPU Piper is the recommended starting point for integrated-graphics laptops.
- **Promptfoo** adds developer-only local evaluation in quality/. It targets BabyMind's loopback API and uses no hosted grader in the included smoke suite.

See Optional integrations (docs/OPTIONAL_INTEGRATIONS.md) and Quality checks (quality/README.md) for setup and privacy boundaries.
