"""Local speech-to-text through optional faster-whisper."""

from __future__ import annotations

from pathlib import Path

from .documents import IntegrationUnavailable


def transcribe_audio(
    path: str | Path,
    *,
    model_size: str = "base",
    language: str | None = None,
    model_cache: str | Path | None = None,
) -> dict[str, object]:
    """Transcribe a local audio file on CPU using INT8 inference by default.

    The first run may download the selected Whisper model into its cache.
    """
    source = Path(path).expanduser()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Local audio file not found: {source}")
    allowed_models = {"tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"}
    if model_size not in allowed_models:
        raise ValueError(f"model_size must be one of: {', '.join(sorted(allowed_models))}")

    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise IntegrationUnavailable(
            'Voice support is optional. Install it with: py -m pip install -e ".[voice]"'
        ) from error

    options: dict[str, object] = {
        "device": "cpu",
        "compute_type": "int8",
    }
    if model_cache is not None:
        options["download_root"] = str(Path(model_cache).expanduser())
    model = WhisperModel(model_size, **options)
    segments, info = model.transcribe(str(source), language=language)
    transcript_segments = [
        {"start": float(item.start), "end": float(item.end), "text": item.text.strip()}
        for item in segments
    ]
    return {
        "language": info.language,
        "language_probability": float(info.language_probability),
        "text": " ".join(item["text"] for item in transcript_segments).strip(),
        "segments": transcript_segments,
        "model": model_size,
        "device": "cpu",
        "compute_type": "int8",
    }
