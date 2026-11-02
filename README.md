# BabyMind

BabyMind is a local-first personal AI application with exactly **50 specialist roles**, one consistent assistant identity, a browser-based interface, optional shared memory, and selectable local model backends (LM Studio or llama.cpp).

The 50 agents are specialist configurations that share one underlying language model. They are not 50 separately trained or separately running models. The optional collaboration mode performs a specialist pass, a quality-review pass, and a final synthesis pass using that same model.

## What is included

- **Chat workspace:** responsive browser UI, conversation history, agent selector, typing indicator, prompt starters, dark/light themes, and Markdown conversation export.
- **Local text attachments:** attach small TXT, Markdown, CSV, JSON, source-code, or config files (up to 12 KB) for model context.
- **50-agent directory:** searchable and filterable BM-01 through BM-50 role catalogue, each with a focused domain playbook and responsibility.
- **Unified coordinator:** one BabyMind identity with role-specific instructions.
- **Collaboration mode:** selected specialist, QualityReviewer (BM-49), then Coordinator (BM-01).
- **Local memory:** opt-in SQLite task/response memories, with controls to view or clear them.
- **Conversation storage:** local SQLite history on the computer running BabyMind.
- **Local model adapters:** LM Studio's OpenAI-compatible API or a BabyMind-managed llama.cpp server using a local GGUF model.
- **CLI:** health, list, ask, route, and memory commands.
- **Lightweight runtime:** core server, storage, and HTTP client use the Python standard library; the desktop window uses pywebview.

## Requirements

- Windows 10/11 and Python 3.10 or newer
- Either [LM Studio](https://lmstudio.ai/) or the [llama.cpp runtime](https://github.com/ggml-org/llama.cpp/releases)
- A compatible local model (LM Studio model or GGUF file)

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
llama.cpp option does not require LM Studio and does not require an API token.
It runs a GGUF model on this computer. The first setup still requires you to
download the runtime and model yourself; BabyMind does not silently download
model files or executable binaries.

### llama.cpp setup on Windows

1. Download the official Windows **x64 CPU** release from
   [ggml-org/llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases).
   Extract it to a folder such as `C:\\BabyMind\\llama.cpp\\`.
2. Obtain a compatible `.gguf` model and save it in a folder such as
   `C:\\BabyMind\\models\\`.
3. In PowerShell, set the paths for your current terminal session:

       $env:BABYMIND_ENGINE = "llama.cpp"
       $env:BABYMIND_LLAMA_SERVER = "C:\\BabyMind\\llama.cpp\\llama-server.exe"
       $env:BABYMIND_GGUF_MODEL = "C:\\BabyMind\\models\\your-model.gguf"

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

Set `BABYMIND_ENGINE=lm-studio` (or remove the variable). LM Studio remains
supported as an optional backend. You can also set `BABYMIND_BASE_URL`,
`BABYMIND_MODEL`, and `BABYMIND_API_KEY` for compatible local servers.

## Start the BabyMind interface

    babymind-web

Then open [http://127.0.0.1:8765](http://127.0.0.1:8765).

On Windows, you can double-click `Start-BabyMind.bat` to install and launch the local app. For iPhone access on the same trusted Wi-Fi network, double-click `Start-BabyMind-iPhone.bat` or run:

    babymind-web --lan

The terminal prints a local network address and a one-time access token. Open that address in Safari on the iPhone and enter the token when prompted. Keep the token private and use this only on a trusted home network. The token protects API access; this is not intended for public internet exposure.


## Windows desktop application

Install and launch BabyMind in its own desktop window (no browser tab required):

    py -m pip install -e .
    babymind-desktop

Or double-click `Start-BabyMind-Desktop.bat`. The first launch installs the
Python package and the pywebview desktop-window dependency. Windows uses the
Microsoft Edge WebView2 runtime; if it is missing, install the official
WebView2 Runtime and launch again.

The desktop window hosts the existing local BabyMind interface. Its local
server binds only to `127.0.0.1`. Build a portable Windows app folder with:

    .\\build-windows.ps1

The output is `dist\\BabyMind\\BabyMind.exe`; copy the entire `dist\\BabyMind`
folder, not just the EXE. The app uses the installed Microsoft Edge WebView2
runtime. The portable build bundles BabyMind and Python, but does not bundle a
model, the llama.cpp runtime, or WebView2. It is not code-signed and is not a
traditional installer yet.

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
- Conversations and memory are stored under `~/.babymind/` by default (or `BABYMIND_HOME`).
- Memory is not automatically written unless the user enables **Remember** for that request.
- No analytics, account service, or cloud model is included in the application.
- The model runner is local; the model's own behavior and resource requirements depend on the selected model and runtime.

## Current capability boundaries

The 50 entries are not independent AI brains: they are 50 focused roles routed to one shared model. Collaboration mode is a sequential multi-pass workflow, not 50 agents reasoning simultaneously. This release does not include unrestricted computer control, autonomous background execution, internet search, or public-internet remote access. Selecting llama.cpp removes the LM Studio dependency, but it does not guarantee unrestricted model behaviour. iPhone use is supported on a trusted local Wi-Fi network with a one-time access token.

## Fixed invariant

BabyMind validates that the canonical registry contains exactly 50 unique, sequential IDs from BM-01 through BM-50.