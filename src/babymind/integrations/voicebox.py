"""Client for the optional, self-hosted Voicebox speech server.

Only loopback HTTP endpoints are accepted. No audio is sent to hosted APIs.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .documents import IntegrationUnavailable


def _base_url() -> str:
    base = os.getenv("BABYMIND_VOICEBOX_URL", "http://127.0.0.1:8790").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Voicebox must use a loopback-only http://127.0.0.1:8790 endpoint.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Voicebox URL must not contain credentials, query strings, or fragments.")
    return base


def _headers(content_type: str | None = None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    key = os.getenv("BABYMIND_VOICEBOX_API_KEY", "").strip()
    if key:
        headers["Authorization"] = "Bearer " + key
    return headers


def voicebox_status(timeout: float = 2.0) -> tuple[bool, str]:
    try:
        request = Request(_base_url() + "/health", headers=_headers())
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(16_384).decode("utf-8"))
        ready = payload.get("status") == "ok" and payload.get("models_loaded") is True
        return ready, "Voicebox speech server is ready." if ready else "Voicebox is reachable but models are not loaded."
    except Exception as error:
        return False, f"Voicebox unavailable: {error}"


def synthesize_speech(text: str, *, voice: str | None = None, speed: float = 1.0) -> bytes:
    clean = text.strip()
    if not clean or len(clean) > 4000:
        raise ValueError("Speech text must contain 1–4,000 characters.")
    if not 0.25 <= float(speed) <= 4.0:
        raise ValueError("Speech speed must be between 0.25 and 4.0.")
    payload: dict[str, object] = {"model": "tts", "input": clean, "speed": float(speed), "response_format": "wav"}
    if voice:
        if len(voice) > 80:
            raise ValueError("Voice identifier is too long.")
        payload["voice"] = voice
    request = Request(
        _base_url() + "/v1/audio/speech",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers("application/json"),
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            audio = response.read(20 * 1024 * 1024 + 1)
    except URLError as error:
        raise IntegrationUnavailable(f"Could not reach local Voicebox: {error}") from error
    if len(audio) > 20 * 1024 * 1024:
        raise ValueError("Voicebox audio response exceeded 20 MB.")
    if not audio.startswith(b"RIFF"):
        raise IntegrationUnavailable("Voicebox did not return a WAV audio file.")
    return audio


def transcribe_with_voicebox(path: str | Path, *, language: str | None = None) -> dict[str, object]:
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Local audio file not found: {source}")
    if source.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("Audio file exceeds the 25 MB Voicebox upload limit.")
    boundary = "BabyMind" + uuid.uuid4().hex
    filename = source.name.replace('"', "")
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nstt\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode(),
        source.read_bytes(),
        b"\r\n",
    ]
    if language:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\n{language[:32]}\r\n".encode())
    parts.append(f"--{boundary}--\r\n".encode())
    request = Request(
        _base_url() + "/v1/audio/transcriptions",
        data=b"".join(parts),
        headers=_headers(f"multipart/form-data; boundary={boundary}"),
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            result = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
    except URLError as error:
        raise IntegrationUnavailable(f"Could not reach local Voicebox: {error}") from error
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise IntegrationUnavailable("Voicebox returned an invalid transcription response.")
    return {"text": result["text"], "language": language, "provider": "Voicebox"}
