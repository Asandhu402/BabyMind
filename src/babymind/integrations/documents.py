"""Local document conversion through optional Docling."""

from __future__ import annotations

from pathlib import Path


class IntegrationUnavailable(RuntimeError):
    """Raised when an optional integration is not installed."""


def convert_document(path: str | Path, *, max_chars: int = 100_000) -> str:
    """Convert one local document to Markdown.

    The function never accepts URLs. Docling may download model assets on its
    first run; after caching, supported conversion can run locally/offline.
    """
    source = Path(path).expanduser()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Local document not found: {source}")
    if source.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("Document exceeds the 100 MB import limit.")
    if max_chars < 1 or max_chars > 1_000_000:
        raise ValueError("max_chars must be between 1 and 1,000,000.")

    try:
        from docling.document_converter import DocumentConverter
    except ImportError as error:
        raise IntegrationUnavailable(
            'Docling is optional. Install it with: py -m pip install -e ".[documents]"'
        ) from error

    result = DocumentConverter().convert(str(source))
    markdown = result.document.export_to_markdown()
    return markdown[:max_chars]
