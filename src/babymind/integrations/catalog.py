"""Discover optional integration availability without importing heavy packages."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class IntegrationStatus:
    integration_id: str
    name: str
    purpose: str
    available: bool
    install_hint: str
    safety: str


def integration_status() -> list[dict[str, object]]:
    """Return serializable status without starting models or downloading assets."""
    try:
        from .voicebox import voicebox_status
        voicebox_ready, voicebox_detail = voicebox_status(timeout=0.5)
    except Exception as error:
        voicebox_ready, voicebox_detail = False, f"Voicebox unavailable: {error}"

    items = (
        IntegrationStatus(
            "docling", "Docling", "Local document parsing and knowledge ingestion",
            importlib.util.find_spec("docling") is not None,
            'py -m pip install -e ".[documents]"',
            "Reads a user-selected local file; conversion output is untrusted content.",
        ),
        IntegrationStatus(
            "faster-whisper", "faster-whisper", "Local speech-to-text transcription",
            importlib.util.find_spec("faster_whisper") is not None,
            'py -m pip install -e ".[voice]"',
            "Processes a user-selected local audio file; model weights may download once.",
        ),
        IntegrationStatus(
            "browser-use", "Browser Use", "Optional supervised local browser automation",
            importlib.util.find_spec("browser_use") is not None,
            'py -m pip install -e ".[browser]"',
            "Can interact with websites; keep supervised and approve each task explicitly.",
        ),
        IntegrationStatus(
            "open-interpreter", "Open Interpreter", "Workspace-scoped coding assistant",
            shutil.which("interpreter") is not None,
            "Install from https://github.com/openinterpreter/openinterpreter",
            "Requires explicit launch approval and a functioning OS workspace sandbox.",
        ),
        IntegrationStatus(
            "cognee", "Cognee", "Optional local knowledge graph and semantic retrieval",
            importlib.util.find_spec("cognee") is not None,
            'py -m pip install -e ".[knowledge-graph]"',
            "Disabled by default. Its separate graph/vector store is not encrypted by BabyMind; index only explicitly approved notes.",
        ),
        IntegrationStatus(
            "voicebox", "Voicebox", "Local speech-to-text and text-to-speech server",
            voicebox_ready,
            "Run the self-hosted server: https://github.com/agjs/voicebox",
            voicebox_detail + " Loopback endpoint only; no cloud speech service.",
        ),
        IntegrationStatus(
            "promptfoo", "Promptfoo", "Local model evaluation and security test harness",
            shutil.which("promptfoo") is not None,
            "Install Node.js 22.22+ and Promptfoo; see quality/README.md",
            "Smoke tests target BabyMind's loopback API; do not configure hosted graders or remote red-team generation.",
        ),
    )
    return [asdict(item) for item in items]
