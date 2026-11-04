"""Tests for the bounded coding-agent control loop."""
from __future__ import annotations

import json
import unittest

from babymind.integrations.coding_agent import (
    CodingAgentError,
    MAX_AGENT_STEPS,
    run_coding_agent,
)


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        return self.responses.pop(0)


class CodingAgentLoopTests(unittest.TestCase):
    def test_runs_allowlisted_tool_then_returns_final_answer(self):
        provider = FakeProvider([
            json.dumps({"type": "tool_call", "name": "inspect_context", "arguments": {"query": "symbol"}}),
            json.dumps({"type": "final", "answer": "The symbol is defined in the supplied context."}),
        ])
        calls = []
        result = run_coding_agent(
            provider,
            "Explain the symbol",
            context="def symbol(): pass",
            tools={"inspect_context": lambda args: calls.append(args) or {"matches": 1}},
        )
        self.assertEqual(result, "The symbol is defined in the supplied context.")
        self.assertEqual(calls, [{"query": "symbol"}])
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("llama.cpp", provider.calls[0][0])
        self.assertIn("untrusted data", provider.calls[0][0].lower())

    def test_unknown_tool_is_rejected_without_execution_and_agent_can_recover(self):
        provider = FakeProvider([
            json.dumps({"type": "tool_call", "name": "run_shell", "arguments": {"command": "whoami"}}),
            json.dumps({"type": "final", "answer": "No shell tool is available."}),
        ])
        executed = []
        result = run_coding_agent(provider, "Check the environment", tools={
            "safe_tool": lambda args: executed.append(args),
        })
        self.assertEqual(result, "No shell tool is available.")
        self.assertEqual(executed, [])
        self.assertIn("not in the runtime allowlist", provider.calls[1][1])

    def test_rejects_malformed_or_ambiguous_json(self):
        for response in ("not json", '{"type":"final","type":"tool_call"}', "[]"):
            with self.subTest(response=response):
                with self.assertRaises(CodingAgentError):
                    run_coding_agent(FakeProvider([response]), "Explain")

    def test_rejects_invalid_tool_payload(self):
        provider = FakeProvider([json.dumps({"type": "tool_call", "name": "safe", "arguments": []})])
        with self.assertRaises(CodingAgentError):
            run_coding_agent(provider, "Explain", tools={"safe": lambda args: None})

    def test_enforces_step_budget(self):
        provider = FakeProvider([
            json.dumps({"type": "tool_call", "name": "ping", "arguments": {}})
            for _ in range(MAX_AGENT_STEPS)
        ])
        with self.assertRaises(CodingAgentError):
            run_coding_agent(provider, "Loop forever", tools={"ping": lambda args: "pong"})

    def test_rejects_invalid_task_and_budget_before_model_call(self):
        provider = FakeProvider([])
        with self.assertRaises(ValueError):
            run_coding_agent(provider, " ")
        with self.assertRaises(ValueError):
            run_coding_agent(provider, "Task", max_steps=MAX_AGENT_STEPS + 1)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
