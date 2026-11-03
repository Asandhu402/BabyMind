"""Output hygiene and evidence checks for local model responses."""

from __future__ import annotations

import re


_REASONING_BLOCK = re.compile(r"<think\b[^>]*>.*?(?:</think\s*>|$)", re.IGNORECASE | re.DOTALL)
_REASONING_TAG = re.compile(r"</?think\b[^>]*>", re.IGNORECASE)


def strip_internal_reasoning(response: str) -> str:
    """Remove leaked reasoning blocks and reject responses with no visible answer."""
    if not isinstance(response, str):
        raise ValueError("Model response must be text.")
    cleaned = _REASONING_BLOCK.sub("", response)
    cleaned = _REASONING_TAG.sub("", cleaned).strip()
    if not cleaned:
        raise ValueError("Model returned no user-facing answer after internal reasoning was removed.")
    return cleaned


def validate_code_review_report(report: str, source: str) -> None:
    """Reject incomplete self-review reports or code evidence not present at its cited line."""
    if not isinstance(report, str) or not report.strip():
        raise ValueError("Self-inspection report is empty.")
    if _REASONING_TAG.search(report):
        raise ValueError("Self-inspection report contains internal reasoning tags.")
    normalized = report.casefold()
    required = ("finding", "evidence", "recommended fix", "tests", "acceptance criteria")
    missing = [heading for heading in required if heading not in normalized]
    if missing:
        raise ValueError("Self-inspection report is missing sections: " + ", ".join(missing))
    if len(report.split()) > 450:
        raise ValueError("Self-inspection report exceeds the 450-word limit.")
    lines = source.splitlines()
    evidence = re.findall(
        r"\bline\s+(\d+)\s*[:—-]\s*`([^`]+)`",
        report,
        flags=re.IGNORECASE,
    )
    verified = False
    for raw_number, quote in evidence:
        number = int(raw_number)
        if 1 <= number <= len(lines) and lines[number - 1].strip() == quote.strip():
            verified = True
            break
    if not verified:
        raise ValueError(
            "Self-inspection report must quote one exact source line as "
            "'Evidence (line N): exact source line' and the line must match."
        )
    if len(report.strip()) < 180:
        raise ValueError("Self-inspection report is too short to contain a useful recommendation.")
