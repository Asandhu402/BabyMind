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


INTEGRATIONS = (
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
        "open-interpreter", "Open Interpreter", "Read-only external coding-agent session",
        shutil.which("interpreter") is not None,
        "Install from https://github.com/openinterpreter/openinterpreter",
        "BabyMind launches it read-only only; never use full-access or approval bypass.",
    ),
)


def integration_status() -> list[dict[str, object]]:
    """Return serializable status for each optional integration."""
    return [asdict(item) for item in INTEGRATIONS]
