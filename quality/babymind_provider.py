"""Promptfoo provider that evaluates the running local BabyMind HTTP app."""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


def call_api(prompt, options, context):
    base = os.getenv("BABYMIND_EVAL_URL", "http://127.0.0.1:8765").rstrip("/")
    if not base.startswith(("http://127.0.0.1:", "http://localhost:")):
        return {"error": "BabyMind eval target must be a loopback HTTP endpoint."}
    payload = json.dumps({
        "message": str(prompt),
        "agent_id": "BM-01",
        "collaborate": False,
        "use_memory": False,
        "remember": False,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = os.getenv("BABYMIND_EVAL_TOKEN", "").strip()
    if token:
        headers["X-BabyMind-Token"] = token
    request = Request(base + "/api/chat", data=payload, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=180) as response:
            result = json.loads(response.read(2_000_000).decode("utf-8"))
        return {"output": str(result.get("response", ""))}
    except Exception as error:
        return {"error": f"Local BabyMind evaluation request failed: {error}"}
