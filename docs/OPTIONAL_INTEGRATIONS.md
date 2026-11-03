# BabyMind integrated capabilities and local engines

BabyMind is one assistant identity, one shared local model, one central coordinator, and 50 specialist role prompts. The capabilities below are implemented in BabyMind's own source tree and are routed through `BabyMindCoordinator`; they do not create competing assistant identities. Some heavyweight engines run as local processes/services so a lightweight Windows installation does not have to load every model at startup.

## Capability map

| Capability | BabyMind core entry point | Local engine |
| --- | --- | --- |
| Document understanding | `BabyMindCoordinator.process_document` | Docling |
| Audio transcription | `process_audio` / `process_voicebox_audio` | faster-whisper or Voicebox |
| Speech output | `synthesize_speech` | Voicebox |
| Knowledge retrieval | `index_knowledge_note` / `ask_with_knowledge` | Cognee |
| Browser tasks | `run_browser_task` | Browser Use |
| Project coding | `launch_coding_session` | Open Interpreter with OS-enforced workspace sandbox |
| Quality/security checks | Repository CI and `quality/` | Promptfoo |

The main app, API and coordinator own the workflows. Upstream projects are used as local engines; their source code is not copied into BabyMind. Keep the engines lazy-loaded and avoid starting multiple large CPU models concurrently.

## Install and start local engines

Install the local Python engines required by the capabilities you use:

    py -m pip install -e ".[documents,voice,browser,knowledge-graph]"

Browser Use requires Python 3.11 or newer. The base application supports Python 3.10. Open Interpreter is a separate CLI distribution and must be installed using its official upstream instructions.

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
archive unrecoverable. On Windows, the inner database keys are DPAPI-protected
for the same Windows user on the same device. Consequently, the current
backup format is for disaster recovery on that installation, not cross-device
or cross-account migration. The archive must be saved outside BabyMind's live
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

Open Interpreter is launched with the local OSS provider, selected local model, `--sandbox workspace-write`, `--ask-for-approval on-request`, and network access disabled. The selected project folder is the permitted workspace for reading, creating, editing, renaming and deleting project files and running project commands. Launch requires approval; escalation requires further approval.

The OS sandbox is the technical boundary, not the confirmation dialog. Native Windows sandboxing must be configured and enforced by Open Interpreter. If enforcement is unavailable, the session must fail closed. BabyMind never selects `danger-full-access`, `--yolo`, or approval-bypass flags. This is project-folder access, not full-PC access.

## Quality and security checks

Promptfoo is a developer/CI test harness, not a second runtime assistant. The checked-in provider targets BabyMind's loopback API. The smoke suite has no hosted grader. Do not add hosted graders or remote red-team generation to privacy-sensitive CI; use local attack/grading models if expanding the suite.

Run the check:

    $env:PROMPTFOO_DISABLE_TELEMETRY = "1"
    $env:BABYMIND_EVAL_URL = "http://127.0.0.1:8765"
    npx promptfoo eval -c quality/promptfooconfig.yaml

## Availability

Use `babymind integrations` to see which local engines are currently available. This is a non-destructive check; it does not start models, download assets, open a browser, or launch a coding agent.
