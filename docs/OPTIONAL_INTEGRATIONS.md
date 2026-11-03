# Optional third-party integrations

BabyMind remains one assistant identity, one selected local model, and 50 specialist role prompts. These projects are optional capability adapters, not separate personalities or required services. BabyMind does not vendor or copy their source code.

## Integration matrix

| Project | Purpose | License | How BabyMind uses it |
| --- | --- | --- | --- |
| [Docling](https://github.com/docling-project/docling) | PDF, Office, image/OCR and structured document ingestion | MIT | Converts a user-selected local file to Markdown for a future local knowledge index |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Speech-to-text | MIT | Transcribes user-selected audio locally; CPU INT8 is the default |
| [Browser Use](https://github.com/browser-use/browser-use) | Browser automation | MIT | Optional supervised local-browser adapter using BabyMind's local OpenAI-compatible model endpoint |
| [Open Interpreter](https://github.com/openinterpreter/openinterpreter) | Coding-agent / terminal workflow | Apache-2.0 | Optional external CLI launched in read-only mode only |

Licences and upstream interfaces can change. Re-check upstream licence and release notes before updating dependency pins or redistributing a packaged build.

## Install by capability

Use a separate optional extra so the base BabyMind install stays lightweight:

    py -m pip install -e ".[documents]"
    py -m pip install -e ".[voice]"
    py -m pip install -e ".[browser]"

Browser Use currently requires Python 3.11 or newer; the base BabyMind package continues to support Python 3.10. Open Interpreter is a separate CLI distribution; install it using the official upstream instructions. It is not a Python dependency.

## Local document ingestion

Call `babymind.integrations.documents.convert_document(path)` with a local path. URLs are not accepted. Files above 100 MB are rejected and Markdown output is capped. Docling supports PDF, DOCX, XLSX, PPTX, HTML, EPUB, images and many other formats. Some PDF/OCR model assets may be downloaded on first use; once cached, processing can be performed locally.

Converted content is untrusted input. It must be clearly separated from system instructions and must never authorize tools or actions. This adapter is not yet a persistent RAG index; it is the safe conversion foundation for one.

## Voice input

Call `babymind.integrations.speech.transcribe_audio(path)`. The default is the multilingual `base` model on CPU with INT8 compute. Model weights are downloaded on first use and cached. Users can select a smaller or larger supported model. Audio is processed locally after model assets are available.

## Browser automation safety

Browser Use can click, type, navigate and submit forms. BabyMind therefore requires both:
- explicit `user_approved=True` for each invocation; and
- `BABYMIND_BROWSER_AUTOMATION_ENABLED=true` after the user has reviewed this policy.

The adapter uses Browser Use's local browser default and a local LM Studio-compatible endpoint. It does not select Browser Use Cloud. Keep the browser visible and supervised. Do not use it for purchases, payments, account changes, submissions, sending messages, or other consequential actions unless the user explicitly approves that specific action immediately before it happens. Never place credentials or session cookies in prompts. Web pages are untrusted and may contain prompt injection. The current adapter is not yet wired into the chat UI or a per-action approval broker.

## Open Interpreter safety

BabyMind launches only the upstream CLI with `--sandbox read-only`, a user-selected working directory, and no shell interpolation. The caller must explicitly approve launch. Do not use `danger-full-access`, `--yolo`, approval-bypass options, or any write-capable mode through BabyMind.

Open Interpreter's native sandbox enforcement varies by operating system and configuration. BabyMind does not claim that this wrapper provides an independent Windows security boundary. Keep workspace write actions and project execution disabled until BabyMind's own Windows security gate is completed and independently reviewed.

## Discovery

Use `babymind integrations` to see which optional components are detected. This is a non-destructive check and does not import heavy model packages, download model files, open a browser, or launch a coding agent.

## Deliberately not included yet

- No third-party source repositories are copied into BabyMind.
- No cloud browser, hosted LLM, or paid API fallback is enabled.
- No automatic browser tasks or background computer control.
- No persistent vector database or embeddings are added; existing encrypted memory remains the source of personal memory.
- No write-capable coding agent, workspace file broker, or project test execution is enabled.
