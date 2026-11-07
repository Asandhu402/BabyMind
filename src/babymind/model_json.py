"""Repair-tolerant JSON parsing for model replies.

Small local models routinely break JSON in predictable ways: they wrap the
object in a Markdown fence, put prose around it, or emit a multi-line string
value with literal newlines. This module parses those replies without guessing
at truncated output.

It used to live in ``orchestrator.py``. The multi-role mission orchestrator was
removed with the 50-role catalogue, but this parser is still used by the
verifier and the server's self-development routes, so it lives here on its own.
"""
from __future__ import annotations

import json


def _strip_code_fence(raw: str) -> str:
    """Drop a Markdown code fence so a scan can find the JSON object.

    The scan ignores any prose the model adds before or after the object, so
    only an opening fence line ("```json") has to be removed.
    """
    text = str(raw or "").strip()
    if text.startswith("```"):
        return text.split("\n", 1)[1] if "\n" in text else text.lstrip("`")
    return text


def _scan_json_object(text: str, start: int) -> str | None:
    """Return the balanced object starting at ``start``, or None if unterminated."""
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _escape_raw_control_characters(text: str) -> str:
    """Escape newlines, tabs and other control characters inside string literals.

    Small models very often emit a multi-line ``"content"`` value with literal
    newlines, which ``json.loads`` rejects with "Invalid control character".
    Escaping them preserves meaning: valid JSON never holds a raw control
    character in a string, so already-valid input comes back unchanged.
    """
    out: list[str] = []
    in_string, escaped = False, False
    for char in text:
        if not in_string:
            if char == '"':
                in_string = True
            out.append(char)
            continue
        if escaped:
            escaped = False
            out.append(char)
        elif char == "\\":
            escaped = True
            out.append(char)
        elif char == '"':
            in_string = False
            out.append(char)
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif ord(char) < 0x20:
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    return "".join(out)


def parse_model_json(raw: str):
    """Parse a model's JSON reply, repairing the mistakes small models make.

    Tries the outermost object first, then later ``{`` positions so a brace in
    the model's prose cannot hide the real object. A truncated reply is never
    guessed at: an incomplete object is reported, not completed, so a caller
    cannot apply half a file.
    """
    text = _strip_code_fence(raw)
    first_error: json.JSONDecodeError | None = None
    searched = 0
    while True:
        start = text.find("{", searched)
        if start == -1:
            break
        searched = start + 1
        candidate = _scan_json_object(text, start)
        if candidate is None:
            if first_error is None:
                raise ValueError(
                    "the model returned an unterminated JSON object; the reply "
                    f"appears to have been cut off after {len(text) - start} characters"
                )
            break
        for variant in (candidate, _escape_raw_control_characters(candidate)):
            try:
                return json.loads(variant)
            except json.JSONDecodeError as error:
                first_error = first_error or error
    if first_error is None:
        raise ValueError("the model returned no JSON object")
    raise ValueError(
        f"the model returned invalid JSON ({first_error.msg} at line {first_error.lineno} "
        f"column {first_error.colno}); it was still invalid after raw newlines and "
        "control characters inside strings were escaped"
    )
