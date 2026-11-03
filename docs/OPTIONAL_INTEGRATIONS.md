# Optional third-party integrations

BabyMind remains one assistant identity, one selected local model, and 50 specialist role prompts. These projects are optional capability adapters, not separate personalities or required services. BabyMind does not vendor or copy their source code.

## Integration matrix

| Project | Purpose | License | How BabyMind uses it |
| --- | --- | --- | --- |
| [Docling](https://github.com/docling-project/docling) | PDF, Office, image/OCR and structured document ingestion | MIT | Converts a user-selected local file to Markdown, then sends bounded text through the core coordinator to the selected local model |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Speech-to-text | MIT | Transcribes user-selected audio locally, then routes the transcript through the core coordinator; CPU INT8 is the default |
| [Browser Use](https://github.com/browser-use/browser-use) | Browser automation | MIT | Optional supervised local-browser adapter using BabyMind's local OpenAI-compatible model endpoint |
| [Open Interpreter](https://github.com/openinterpreter/openinterpreter) | Coding-agent / terminal workflow | Apache-2.0 | External CLI launched with workspace-scoped write access and on-request approvals |

Licences and upstream interfaces can change. Re-check upstream licence and release notes before updating dependency pins or redistributing a packaged build.

## Install by capability

Use a separate optional extra so the base BabyMind install stays lightweight:

    py -m pip install -e ".[documents]"
    py -m pip install -e ".[voice]"
    py -m pip install -e ".[browser]"

Browser Use currently requires Python 3.11 or newer; the base BabyMind package continues to support Python 3.10. Open Interpreter is a separate CLI distribution; install it using the official upstream instructions. It is not a Python dependency.

## Local document ingestion

Open Settings → Connected tools. Enter a local file path and an instruction, then choose Analyze document. The server calls `BabyMindCoordinator.process_document`, converts the file with `convert_document`, and sends the extracted text through the same selected model and agent role. URLs are not accepted. Files above 100 MB are rejected and Markdown output is capped. Some PDF/OCR model assets may be downloaded on first use; once cached, processing can be performed locally.

Converted content is untrusted input and is clearly separated from system instructions. It cannot authorize tools or actions. This is direct document analysis, not a persistent RAG index; no separate vector database or duplicate memory store is created.

## Voice input

Open Settings → Connected tools, enter a local audio path and an instruction, then choose Transcribe and analyze. The coordinator calls `transcribe_audio` and routes the resulting transcript through the same local model. The default is the multilingual `base` model on CPU with INT8 compute. Model weights are downloaded on first use and cached.

## Browser automation safety

Browser Use can click, type, navigate and submit forms. BabyMind therefore requires both:
- explicit `user_approved=True` for each invocation; and
- browser automation is enabled by default; set `BABYMIND_BROWSER_AUTOMATION_ENABLED=false` to disable it.

The adapter uses Browser Use's local browser default and a local LM Studio-compatible endpoint. It does not select Browser Use Cloud. The user must approve each task in BabyMind's confirmation dialog. Keep the browser visible and supervised. Do not delegate purchases, payments, account changes, submissions, sending messages, or other consequential actions to this task-level automation. Never place credentials or session cookies in prompts. Web pages are untrusted and may contain prompt injection. The integration is available from Settings → Connected tools. BabyMind requires a confirmation dialog for each task, the API requires `user_approved=True`, and the environment gate must also be enabled. This is task-level approval, not an independent approval dialog for every click; keep the browser visible and supervise the whole run. Do not delegate consequential actions.

## Open Interpreter project access

BabyMind launches the upstream CLI with the documented local OSS provider flags (`--oss --local-provider lmstudio`), passes BabyMind's loopback model endpoint through `CODEX_OSS_BASE_URL`, selects the active local model ID, and starts in the selected project directory with `--sandbox workspace-write` and `--ask-for-approval on-request`. The workspace-write sandbox allows the agent to read, create, edit, rename and delete project files and run project commands inside the selected workspace. Network access is explicitly disabled. The user must approve each launch; the agent asks before actions requiring broader permissions. The wrapper uses no shell interpolation and never selects `danger-full-access`, `--yolo`, or approval-bypass options.

The sandbox is the technical boundary, not the confirmation dialog. Open Interpreter documents native Windows sandboxing when configured and says it fails closed when the requested policy cannot be enforced. BabyMind does not add an independent Windows kernel sandbox. Keep secrets out of the project folder, and review any request to access outside the workspace or enable network access. This is project-folder access, not full-PC access.

## Discovery

Use `babymind integrations` to see which optional components are detected. This is a non-destructive check and does not import heavy model packages, download model files, open a browser, or launch a coding agent.

## Deliberately not included yet

- No third-party source repositories are copied into BabyMind.
- No cloud browser, hosted LLM, or paid API fallback is enabled.
- No unattended browser tasks or background computer control.
- No persistent vector database or embeddings are added; existing encrypted memory remains the source of personal memory.
- No write-capable coding agent, workspace file broker, or project test execution is enabled.
