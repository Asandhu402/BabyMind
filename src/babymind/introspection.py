"""Metacognitive self-review for BabyMind.

This module is the "catches itself thinking" half of BabyMind's metacognition.
Instead of emitting the first plausible completion, BabyMind can:

1. **Assess** the request before answering: what is actually being asked, what
   it does and does not know, what it would have to assume, and whether the
   request rests on a premise it should push back on.
2. **Draft** an answer.
3. **Critique** its own draft as if it were someone else's: factual errors,
   unsupported claims, sycophancy, evasions, missed parts of the question.
4. **Revise** only when the critique found something worth fixing.
5. **Report** what it checked, what it assumed, and where it disagrees.

The critique is model-generated text about model-generated text. That makes it a
second opinion from the same 4B model, not an independent check. It reliably
catches a class of errors -- overclaiming, missing the question, reflexive
agreement -- and it cannot be relied on to catch deep factual or reasoning
errors. The module records that limitation rather than hiding it.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

MAX_TEXT = 4000


class SupportsComplete(Protocol):
    def complete(self, system_prompt: str, user_prompt: str) -> str: ...


def _clean(value: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clamp(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def _string_list(value: Any, limit: int = 8, item_limit: int = 300) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:limit]:
        text = _clean(item, item_limit)
        if text:
            out.append(text)
    return out


class _JSONParseError(ValueError):
    """Raised when a model stage fails to return a usable JSON object."""


def _extract_json(raw: str) -> dict[str, Any]:
    """Pull one JSON object out of a model response, tolerating fences."""
    text = (raw or "").strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        text = text.split("\n", 1)[-1]
        remainder = text.split(fence)
        text = remainder[0] if remainder else text
    text = text.strip()
    if text.lower().startswith("json"):
        text = text[4:].strip()
    # Fall back to the outermost balanced object when the model adds prose.
    if not text.startswith("{"):
        start, depth, in_string, escaped = -1, 0, False, False
        for index, char in enumerate(text):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
            elif char == '"':
                in_string = not in_string
            elif not in_string:
                if char == "{":
                    if depth == 0:
                        start = index
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0 and start >= 0:
                        text = text[start : index + 1]
                        break
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise _JSONParseError(f"Model stage did not return valid JSON: {error.msg}") from error
    if not isinstance(parsed, dict):
        raise _JSONParseError("Model stage must return a JSON object.")
    return parsed


def _stage(provider: SupportsComplete, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    return _extract_json(provider.complete(system_prompt, user_prompt))


# --------------------------------------------------------------------- stages

ASSESS_SYSTEM = (
    "You are the pre-answer assessment stage of one software system, reviewing a request "
    "before it commits to an answer. Be honest about the limits of what you know. "
    "Your job is not to please the asker; it is to establish what is actually true and "
    "what is actually being asked. Return one JSON object with these keys:\n"
    "  restated_request: the question in your own words.\n"
    "  false_premise: string. If the request assumes something untrue or misleading, name it "
    "precisely. Empty string if the request is sound.\n"
    "  what_i_know: array of strings, facts relevant to answering that you can support.\n"
    "  what_i_do_not_know: array of strings, things that would change the answer.\n"
    "  assumptions_required: array of strings, assumptions you would have to make.\n"
    "  sycophancy_risk: number 0..1, how tempted you are to agree with the asker rather than "
    "be accurate. Rate it honestly.\n"
    "  should_push_back: boolean. True when answering as asked would require you to affirm "
    "something false, or to hide a material problem.\n"
    "  push_back: string. What you would say instead, if should_push_back is true.\n"
    "  confidence_before: number 0..1, your confidence that you can answer well.\n"
    "Return only the JSON object. No prose before or after it."
)

CRITIQUE_SYSTEM = (
    "You are the self-critique stage of one software system. You are reading a draft answer "
    "that you yourself produced moments ago. Treat it as if a colleague wrote it and your job "
    "is to find what is wrong before anyone else sees it. Do not be gentle for the sake of "
    "being gentle, and do not invent problems to appear rigorous. Return one JSON object:\n"
    "  factual_errors: array of strings. Claims that are wrong or very likely wrong.\n"
    "  unsupported_claims: array of strings. Assertions presented as fact with no support.\n"
    "  missed_the_question: string. What the draft failed to address, or empty string.\n"
    "  sycophancy: string. Where the draft agrees with the asker, flatters, or softens a true "
    "point to be agreeable. Empty string if none.\n"
    "  overconfidence: string. Where the draft sounds more certain than the evidence allows.\n"
    "  unclear: array of strings. Passages a careful reader would find ambiguous or padded.\n"
    "  verdict: one of \"sound\", \"needs_revision\", \"wrong_framing\".\n"
    "  most_important_fix: string. The single change that would most improve the answer.\n"
    "Return only the JSON object. No prose before or after it."
)

REVISE_SYSTEM = (
    "You are the revision stage of one software system. Rewrite the draft using the critique. "
    "Fix what the critique identified and leave everything else alone. Do not announce that you "
    "are revising, do not mention the critique process, and do not add apologies or meta-commentary "
    "about being an AI. Keep the answer aimed at the actual question. Return one JSON object with "
    "exactly two keys: \"answer\" (the revised answer, in full) and \"what_changed\" (a short "
    "string describing what you changed and why). Return only the JSON object."
)


def assess(provider: SupportsComplete, task: str, *, context: str = "") -> dict[str, Any]:
    """Establish what is being asked and whether it should be pushed back on."""
    user = (
        f"REQUEST:\n{_clean(task, 8000)}\n"
        f"\nADDITIONAL CONTEXT:\n{_clean(context, 4000) or '(none)'}\n"
        "\nAssess this request before answering it."
    )
    raw = _stage(provider, ASSESS_SYSTEM, user)
    return {
        "restated_request": _clean(raw.get("restated_request")),
        "false_premise": _clean(raw.get("false_premise"), 1200),
        "what_i_know": _string_list(raw.get("what_i_know")),
        "what_i_do_not_know": _string_list(raw.get("what_i_do_not_know")),
        "assumptions_required": _string_list(raw.get("assumptions_required")),
        "sycophancy_risk": _clamp(raw.get("sycophancy_risk"), 0.0),
        "should_push_back": bool(raw.get("should_push_back")),
        "push_back": _clean(raw.get("push_back"), 1500),
        "confidence_before": _clamp(raw.get("confidence_before")),
    }


def critique(
    provider: SupportsComplete, task: str, draft: str, *, assessment: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Critique a draft answer as though it came from someone else."""
    user = (
        f"ORIGINAL REQUEST:\n{_clean(task, 8000)}\n\n"
        f"YOUR DRAFT ANSWER:\n{_clean(draft, 8000)}\n"
    )
    if assessment:
        user += (
            "\nWHAT YOU NOTED BEFORE DRAFTING (check the draft honoured it):\n"
            + json.dumps(assessment, ensure_ascii=False)
            + "\n"
        )
    user += "\nCritique the draft."
    raw = _stage(provider, CRITIQUE_SYSTEM, user)
    verdict = _clean(raw.get("verdict"), 40).lower()
    if verdict not in ("sound", "needs_revision", "wrong_framing"):
        verdict = "needs_revision"
    return {
        "factual_errors": _string_list(raw.get("factual_errors")),
        "unsupported_claims": _string_list(raw.get("unsupported_claims")),
        "missed_the_question": _clean(raw.get("missed_the_question"), 1200),
        "sycophancy": _clean(raw.get("sycophancy"), 1200),
        "overconfidence": _clean(raw.get("overconfidence"), 1200),
        "unclear": _string_list(raw.get("unclear")),
        "verdict": verdict,
        "most_important_fix": _clean(raw.get("most_important_fix"), 1200),
    }


def revise(
    provider: SupportsComplete, task: str, draft: str, review: dict[str, Any]
) -> tuple[str, str]:
    """Produce a revised answer from a critique. Returns (answer, what_changed)."""
    user = (
        f"ORIGINAL REQUEST:\n{_clean(task, 8000)}\n\n"
        f"DRAFT:\n{_clean(draft, 8000)}\n\n"
        f"CRITIQUE:\n{json.dumps(review, ensure_ascii=False)}\n\n"
        "Apply the critique and return the revised answer."
    )
    raw = _stage(provider, REVISE_SYSTEM, user)
    answer = _clean(raw.get("answer"), 12000)
    if not answer:
        raise _JSONParseError("Revision stage returned an empty answer.")
    return answer, _clean(raw.get("what_changed"), 1200)


# ------------------------------------------------------------------- pipeline

@dataclass(frozen=True, slots=True)
class IntrospectionResult:
    """A response plus the honest account of how it was arrived at."""

    response: str
    draft: str
    revised: bool
    what_changed: str
    assessment: dict[str, Any]
    review: dict[str, Any]
    initial_review: dict[str, Any]
    confidence: float
    dissent: str
    assumptions: list[str]
    unverified: list[str]
    stages_run: tuple[str, ...] = ()
    degraded: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "draft": self.draft,
            "revised": self.revised,
            "what_changed": self.what_changed,
            "assessment": self.assessment,
            "review": self.review,
            "initial_review": self.initial_review,
            "confidence": self.confidence,
            "dissent": self.dissent,
            "assumptions": list(self.assumptions),
            "unverified": list(self.unverified),
            "stages_run": list(self.stages_run),
            "degraded": self.degraded,
        }


_NEEDS_WORK = ("needs_revision", "wrong_framing")


def run_introspection(
    provider: SupportsComplete,
    task: str,
    *,
    draft_fn=None,
    context: str = "",
    max_revisions: int = 1,
    skip_assessment: bool = False,
) -> IntrospectionResult:
    """Draft, self-critique and - where warranted - revise one answer.

    ``draft_fn`` produces the first answer; it receives ``(task, context)`` and
    may be any callable that returns text (BabyMind's coordinator passes a
    role-aware call). When a stage fails the pipeline degrades to the best
    answer it already has rather than failing the request.
    """
    if draft_fn is None:
        raise ValueError("run_introspection requires a draft_fn that produces the first answer.")
    stages: list[str] = ["draft"]
    degraded = ""

    draft = _clean(draft_fn(task, context), 12000)
    if not draft:
        raise ValueError("The draft stage returned an empty answer.")

    assessment: dict[str, Any] = {}
    if not skip_assessment:
        try:
            assessment = assess(provider, task, context=context)
            stages.append("assess")
        except Exception as error:  # noqa: BLE001 - a failed stage must not lose the answer
            degraded = f"Assessment stage failed: {str(error)[:200]}"
            assessment = {}

    try:
        review = critique(provider, task, draft, assessment=assessment or None)
        stages.append("critique")
    except Exception as error:  # noqa: BLE001
        degraded = (degraded + " " if degraded else "") + f"Critique stage failed: {str(error)[:200]}"
        review = {"verdict": "sound", "most_important_fix": "", "factual_errors": [],
                  "unsupported_claims": [], "missed_the_question": "", "sycophancy": "",
                  "overconfidence": "", "unclear": []}

    # Keep the first critique: what was wrong with the *first* attempt says
    # something real about how reliable this answer is, even when the shipped
    # text is clean.
    initial_review = review

    response = draft
    revised = False
    what_changed = ""
    revisions = 0
    while review.get("verdict") in _NEEDS_WORK and revisions < max(0, max_revisions):
        try:
            response, what_changed = revise(provider, task, response, review)
            revised = True
            revisions += 1
            stages.append("revise")
        except Exception as error:  # noqa: BLE001
            degraded = (degraded + " " if degraded else "") + (
                f"Revision stage failed: {str(error)[:200]}"
            )
            response = draft
            revised = False
            what_changed = ""
            break
        # Re-critique the revision so the recorded verdict describes what ships.
        # If this fails, the pre-revision critique stands: it is the last honest
        # thing we know about a draft we have since replaced.
        try:
            review = critique(provider, task, response, assessment=assessment or None)
        except Exception as error:  # noqa: BLE001
            degraded = (degraded + " " if degraded else "") + (
                f"Re-critique failed: {str(error)[:200]}"
            )
            break

    dissent = ""
    if assessment.get("should_push_back"):
        dissent = _clean(assessment.get("push_back"), 1500)
    elif assessment.get("false_premise"):
        dissent = _clean(assessment.get("false_premise"), 1500)
    if not dissent and initial_review.get("verdict") == "wrong_framing":
        dissent = _clean(initial_review.get("most_important_fix"), 1500)

    # Confidence: start from the pre-answer estimate and discount for what the
    # first critique actually found. This is a heuristic, not a measurement.
    confidence = _clamp(assessment.get("confidence_before"), 0.5) if assessment else 0.5
    if initial_review.get("factual_errors"):
        confidence = max(0.05, confidence - 0.3)
    if initial_review.get("unsupported_claims"):
        confidence = max(0.05, confidence - 0.15)
    if initial_review.get("missed_the_question"):
        confidence = max(0.05, confidence - 0.15)
    if revised:
        # Revising recovers some ground, never all of it: a first attempt that
        # needed correcting is evidence the answer was not easy to get right.
        confidence = min(1.0, confidence + 0.1)
    if review.get("verdict") in _NEEDS_WORK:
        # Still flagged after revision.
        confidence = max(0.05, confidence - 0.15)
    if degraded:
        confidence = max(0.05, confidence - 0.1)

    return IntrospectionResult(
        response=response,
        draft=draft,
        revised=revised,
        what_changed=what_changed,
        assessment=assessment,
        review=review,
        initial_review=initial_review,
        confidence=round(confidence, 3),
        dissent=dissent,
        assumptions=list(assessment.get("assumptions_required") or []),
        unverified=list(assessment.get("what_i_do_not_know") or []),
        stages_run=tuple(stages),
        degraded=degraded.strip(),
    )


_LEAD_IN = re.compile(
    r"^\s*(certainly|of course|great question|absolutely|you'?re (?:absolutely |totally )?(?:right|correct))[,!.]?\s+",
    re.IGNORECASE,
)


def independent_thinker_directive() -> str:
    """Instructions that make BabyMind reason for itself rather than defer."""
    return (
        "INDEPENDENT REASONING:\n"
        "- Work the problem out yourself before considering what the user seems to want to hear. "
        "Agreement is a conclusion you reach, not a default you start from.\n"
        "- If the request assumes something false, name the false premise first and then answer "
        "the question that was probably intended. Do not build on a premise you believe is wrong.\n"
        "- If the user's plan has a serious flaw, say so plainly and specifically, then help anyway "
        "if they still want to proceed. Being useful and being agreeable are different things.\n"
        "- Do not open with flattery. Do not tell the user their question is good.\n"
        "- Where you are uncertain, mark the uncertainty and say what would settle it, rather than "
        "hedging vaguely or overclaiming to seem decisive.\n"
        "- You are allowed to hold a view the user disagrees with. Say it, give the reason, and let "
        "them weigh it."
    )


def strip_reflexive_agreement(text: str) -> str:
    """Remove the automatic 'Certainly!' / 'You're absolutely right' opener."""
    previous = text
    for _ in range(3):
        stripped = _LEAD_IN.sub("", previous, count=1)
        if stripped == previous:
            break
        previous = stripped
    return previous
