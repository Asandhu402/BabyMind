"""Supervised local browser automation through optional Browser Use."""

from __future__ import annotations

import os

from .documents import IntegrationUnavailable


async def run_browser_task(
    task: str,
    *,
    model: str,
    base_url: str = "http://127.0.0.1:1234/v1",
    api_key: str = "lm-studio",
    user_approved: bool = False,
) -> str:
    """Run a Browser Use task against a local OpenAI-compatible model.

    This adapter always selects a local browser (never Browser Use Cloud).
    The caller must obtain explicit approval before invoking it. The task may
    still cause website state changes, so it must run visibly under supervision.
    """
    if not user_approved:
        raise PermissionError("Browser automation requires explicit user approval.")
    clean_task = task.strip()
    if not clean_task or len(clean_task) > 4_000:
        raise ValueError("Browser task must contain 1–4,000 characters.")
    if not base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("Browser Use model endpoint must be local to this computer.")
    if os.getenv("BABYMIND_BROWSER_AUTOMATION_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        raise PermissionError(
            "Browser automation is disabled by BABYMIND_BROWSER_AUTOMATION_ENABLED."
        )

    try:
        from browser_use import Agent, Browser, ChatOpenAI
    except ImportError as error:
        raise IntegrationUnavailable(
            'Browser Use is optional. Install it with: py -m pip install -e ".[browser]"'
        ) from error

    llm = ChatOpenAI(
        model=model,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
    )
    browser = Browser()
    agent = Agent(task=clean_task, llm=llm, browser=browser)
    try:
        history = await agent.run()
        final_result = history.final_result()
        return str(final_result or "").strip()
    finally:
        await browser.close()
