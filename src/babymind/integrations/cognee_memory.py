"""Explicitly opt-in local knowledge-graph adapter for Cognee.

Cognee maintains its own local graph/vector store. That store is separate from
BabyMind's AES-encrypted SQLite memory and is NOT encrypted by BabyMind.
Nothing is indexed automatically.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from .documents import IntegrationUnavailable


def _enabled() -> None:
    if os.getenv("BABYMIND_COGNEE_ENABLED", "").strip().lower() not in {"1", "true", "yes"}:
        raise PermissionError("Cognee indexing is disabled. Set BABYMIND_COGNEE_ENABLED=true after reviewing its separate local storage privacy warning.")
    hosted_keys = ("OPENAI_API_KEY", "OPENAI_TOKEN", "LLM_API_KEY", "ANTHROPIC_API_KEY")
    if any(os.getenv(name, "").strip() for name in hosted_keys):
        raise PermissionError("Remove hosted-model API keys from this process before enabling the local-only Cognee adapter.")


def _sdk() -> Any:
    try:
        import cognee
    except ImportError as error:
        raise IntegrationUnavailable('Cognee is optional. Install with: py -m pip install -e ".[knowledge-graph]"') from error
    return cognee


def index_approved_note(text: str, *, dataset: str = "babymind-approved") -> str:
    """Index one user-approved note using local extraction and local embeddings."""
    _enabled()
    clean = text.strip()
    if not clean or len(clean) > 20_000:
        raise ValueError("Knowledge note must contain 1–20,000 characters.")
    if not dataset.replace("-", "").replace("_", "").isalnum() or len(dataset) > 64:
        raise ValueError("Invalid Cognee dataset name.")
    cognee = _sdk()

    async def run() -> None:
        await cognee.add(clean, dataset_name=dataset)
        await cognee.cognify(
            datasets=dataset,
            extractor="gliner_demo",
            summary_method="from_extraction",
        )

    asyncio.run(run())
    return dataset


def search_approved_notes(query: str, *, dataset: str = "babymind-approved") -> list[str]:
    """Search only the explicitly selected local Cognee dataset."""
    _enabled()
    clean = query.strip()
    if not clean or len(clean) > 1000:
        raise ValueError("Knowledge search must contain 1–1,000 characters.")
    cognee = _sdk()

    async def run() -> list[str]:
        from cognee import SearchType
        results = await cognee.search(
            query_text=clean,
            query_type=SearchType.CHUNKS,
            datasets=[dataset],
        )
        return [str(item)[:4000] for item in (results or [])][:10]

    return asyncio.run(run())
