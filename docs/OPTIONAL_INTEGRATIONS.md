# BabyMind integrated capabilities and local engines

BabyMind is one assistant identity, one shared local model, one central coordinator, and 50 specialist role prompts. The capabilities below are implemented in BabyMind's own source tree and are routed through `BabyMindCoordinator`; they do not create competing assistant identities. Some heavyweight engines run as local processes/services so a lightweight Linux installation does not have to load every model at startup.

## Capability map

| Capability | BabyMind core entry point | Local engine |
| --- | --- | --- |
| Document understanding | `BabyMindCoordinator.process_document` | Docling |
| Audio transcription | `process_audio` / `process_voicebox_audio` | faster-whisper or Voicebox |
| Speech output | `synthesize_speech` | Voicebox |
| Knowledge retrieval | `index_knowledge_note` / `ask_with_knowledge` | Cognee |
| Browser tasks | `run_browser_task` | Browser Use |
| Project coding | Disabled | Waiting for a verified llama.cpp-native coding adapter and OS-enforced workspace sandbox |
| Quality/security checks | Repository CI and `quality/` | Promptfoo |

The main app, API and coordinator own the workflows. Upstream projects are used as local engines; their source code is not copied into BabyMind. Keep the engines lazy-loaded and avoid starting multiple large CPU models concurrently.

## Install and start local engines

Install the local Python engines required by the capabilities you use:

    python3 -m pip install -e ".[documents,voice,browser,knowledge-graph]"

Browser Use requires Python 3.11 or newer. The base application supports Python 3.10. The external coding CLI adapter is intentionally disabled until it can use BabyMind's llama.cpp runtime directly.

Voicebox runs as a self-hosted loopback service. Example:

    docker run --rm -p 127.0.0.1:8790:8790 ghcr.io/agjs/voicebox:0.2.16

BabyMind accepts only loopback HTTP endpoints for Voicebox. Use CPU Piper and a small/distilled speech model first on integrated-graphics laptops. Docker and model downloads require additional disk/RAM. Voicebox audio does not go to a hosted speech API.

## Encrypted backup and restore

The core Settings screen can create and restore password-protected `.bmbak`
archives. The archive encrypts the existing encrypted SQLite database and key
files as a single authenticated payload using scrypt and AES-256-GCM. No
plaintext conversation or memory export is created. The restore process
checks the archive format, file allowlist, checksums, SQLite integrity and
whether the supplied keys decrypt the stored text before replacing live files.
It stages the replacement and rolls back changed files if a replacement fails.

The backup password must be at least 12 characters. Losing it makes the
archive unrecoverable. The Linux key files are stored with owner-only permissions and are included in the encrypted archive. Protect the archive password and keep the archive outside the live data directory. The archive must be saved outside BabyMind's live
data directory. After a restore, close and reopen BabyMind.

## Shared coordinator and memory

All speech transcription and knowledge-search answers pass through the same BabyMind coordinator and selected local model. Knowledge-search answers can also use the existing encrypted BabyMind memory when the user enables memory. Integration exchanges are stored in BabyMind's encrypted conversation history.

Cognee's graph/vector index is a separate local data store and is NOT encrypted by BabyMind's AES-GCM SQLite memory. For now:
- Index only notes the user explicitly approves in the UI.
- BabyMind never copies all conversations or encrypted personal memories into Cognee.
- Do not index passwords, tokens, financial identifiers, or other secrets.
- Review Cognee's storage directory and back it up/delete it separately.
- The coordinator refuses Cognee indexing when common hosted-model API-key variables are present.

This boundary is deliberate: do not claim Cognee data is encrypted. A future encrypted knowledge-store migration must be designed and tested before automatic indexing is enabled.

## Document understanding

Open Settings → Connected tools. Enter a local file path and an instruction, then choose Analyze document. URLs are not accepted. Files above 100 MB are rejected and Markdown output is capped. Some OCR/model assets may download on first use; after caching, supported processing can run locally. Extracted document text is treated as untrusted input and cannot authorize tools or actions.

## Speech

Settings provides local audio transcription through faster-whisper or Voicebox and local text-to-speech through Voicebox. Transcripts are routed through BabyMind's shared coordinator, memory settings and encrypted conversation history. Speech models may need a one-time local download. Check the Voicebox service status before using speech output.

## Browser automation safety

Browser Use runs a visible local browser against BabyMind's local model endpoint. Each task requires explicit user approval and the environment gate must remain enabled. This is task-level approval, not an independent approval dialog for every click; keep the browser visible and supervise the entire run. Do not delegate purchases, payments, account changes, submissions, sending messages, or other consequential actions. Web pages are untrusted and may contain prompt injection.

## Project coding safety

The external coding CLI adapter is currently disabled. The previous CLI integration selected a separate local-model provider rather than BabyMind's llama.cpp server. BabyMind now fails closed instead of launching a different model runtime. Re-enable coding only after an implementation can connect directly to llama.cpp and enforce the selected workspace boundary with a reviewed OS-level sandbox.
## Quality and security checks

Promptfoo is a developer/CI test harness, not a second runtime assistant. The checked-in provider targets BabyMind's loopback API. The smoke suite has no hosted grader. Do not add hosted graders or remote red-team generation to privacy-sensitive CI; use local attack/grading models if expanding the suite.

Run the check:

    $env:PROMPTFOO_DISABLE_TELEMETRY = "1"
    $env:BABYMIND_EVAL_URL = "http://127.0.0.1:8765"
    npx promptfoo eval -c quality/promptfooconfig.yaml

## Availability

Use `babymind integrations` to see which local engines are currently available. This is a non-destructive check; it does not start models, download assets, open a browser, or launch a coding agent.
