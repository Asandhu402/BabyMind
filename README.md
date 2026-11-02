# BabyMind

BabyMind is a local-first personal AI application with exactly **50 specialist roles**, one consistent assistant identity, a browser-based interface, optional shared memory, and an LM Studio model connection.

The 50 agents are specialist configurations that share one underlying language model. They are not 50 separately trained or separately running models. The optional collaboration mode performs a specialist pass, a quality-review pass, and a final synthesis pass using that same model.

## What is included

- **Chat workspace:** responsive browser UI, conversation history, agent selector, typing indicator, prompt starters, dark/light themes, and Markdown conversation export.
- **Local text attachments:** attach small TXT, Markdown, CSV, JSON, source-code, or config files (up to 12 KB) for model context.
- **50-agent directory:** searchable and filterable BM-01 through BM-50 role catalogue, each with a focused domain playbook and responsibility.
- **Unified coordinator:** one BabyMind identity with role-specific instructions.
- **Collaboration mode:** selected specialist, QualityReviewer (BM-49), then Coordinator (BM-01).
- **Local memory:** opt-in SQLite task/response memories, with controls to view or clear them.
- **Conversation storage:** local SQLite history on the computer running BabyMind.
- **Local model adapter:** LM Studio's OpenAI-compatible API.
- **CLI:** health, list, ask, route, and memory commands.
- **No runtime Python dependencies:** server, storage, and model HTTP client use the Python standard library.

## Requirements

- Python 3.10 or newer
- [LM Studio](https://lmstudio.ai/) for local model inference
- A local model compatible with LM Studio's chat-completions endpoint

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
server binds only to `127.0.0.1`; model inference still uses the configured
local LM Studio server. This launcher is a desktop-window version, not yet a
self-contained signed `.exe` installer.

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
- `ask` sends the request to LM Studio with the selected role instructions.
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
- The model runner is local; the model's own behavior and resource requirements depend on the model selected in LM Studio.

## Current capability boundaries

The 50 entries are not independent AI brains: they are 50 focused roles routed to one shared model. Collaboration mode is a sequential multi-pass workflow, not 50 agents reasoning simultaneously. This release does not include unrestricted computer control, autonomous background execution, internet search, or public-internet remote access. iPhone use is supported on a trusted local Wi-Fi network with a one-time access token.

## Fixed invariant

BabyMind validates that the canonical registry contains exactly 50 unique, sequential IDs from BM-01 through BM-50.