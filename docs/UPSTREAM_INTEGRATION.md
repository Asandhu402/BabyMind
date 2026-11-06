# Upstream integration research

`src/babymind/integrations/upstream_components.py` records Linux-relevant
references. These entries and the optional uninitialized Git submodules are
research material, not enabled integrations or trusted dependencies. Do not
execute imported code automatically. Review a specific commit, source, licenses,
dependencies and security behavior before adopting any project; maintain
attribution and test it on the actual Linux target. No cloud model service,
Docker installation or paid account is required by the core app.

The namespace sandbox is not a workspace authorization broker. The app builder
requests sandboxed execution and fails closed when the backend is unavailable.
Source-mode `auto` can fall back to uncontained execution only when explicitly
allowed; use `require` for untrusted commands. See [security policy](../SECURITY.md)
and [limitations](KNOWN_LIMITATIONS.md).

## Coding-agent research (2026-11-06)

We inspected Aider's repository-map implementation (Apache-2.0), SWE-agent's
file-map/reproduction/review configuration (MIT), and the OpenHands SDK and
OpenHands repository metadata (MIT). Aider uses tree-sitter-based symbol maps
and additional dependencies; SWE-agent and OpenHands expose much broader
execution environments. We did not vendor code or enable those environments.
BabyMind's small standard-library lexical selector is an independently written,
bounded first step, not an equivalent to these projects' agents or repository
maps. Upstream licenses and dependency/security review must be repeated at the
specific pinned revision before any future code integration.

## Upstream architecture review (2026-11-06)

The following source files were inspected; no upstream code or dependencies
were copied or bundled:

- [OpenHands conversation adapter](https://github.com/OpenHands/OpenHands/blob/54abf0114a40b610e2dfabb1b263dc145664d0a6/src/api/conversation-service/agent-server-conversation-service.api.ts)
  (MIT) separates conversation UI from the agent backend. The companion
  [SDK response dispatcher](https://github.com/OpenHands/software-agent-sdk/blob/893ca2ed1ebef3dc929f2a734c805d285e9490fd/openhands-sdk/openhands/sdk/agent/response_dispatch.py)
  (MIT) distinguishes tool calls from content and empty responses. BabyMind's
  existing coding engine remains a much smaller, self-development-only loop.
- [bolt.diy action runner](https://github.com/stackblitz-labs/bolt.diy/blob/353b44c8f386aeb15abdf277515d78ff50f7578e/app/lib/runtime/action-runner.ts)
  (MIT) tracks action lifecycle and abort state; its workbench composes editor,
  files, previews, and terminal stores around WebContainer. BabyMind does not
  import WebContainer or claim this workbench's terminal/preview/deployment.
- [GPT Researcher deep research](https://github.com/assafelovic/gpt-researcher/blob/3582a6841fe7dc801e2a34e34ee408641aea9bce/gpt_researcher/skills/deep_research.py)
  (Apache-2.0) plans search queries and controls breadth, depth and concurrency.
  BabyMind independently implements a small single-depth, bounded query and
  evidence pipeline; it does not integrate the project or its agent system.
- [Letta Code memory](https://github.com/letta-ai/letta-code/blob/6d56a5a8e66bf628f38b8864f2b9fe5859934c8c/src/agent/memory.ts)
  (Apache-2.0) distinguishes persona and human memory blocks. BabyMind's
  independently implemented user-edited encrypted context card is simpler and
  is not automatically learned or agent-managed.

This is a focused integration of ideas into existing BabyMind modules, not a
feature-equivalence claim. See [research engine limitations](RESEARCH_ENGINE.md).

## Team and memory/sandbox architecture review (2026-11-06)

These are source reviews, not imported projects. No upstream code was copied,
no dependencies were added, and the changes do not provide equivalent runtimes.

- [LangGraph state graph and Pregel loop](https://github.com/langchain-ai/langgraph/blob/e5e37b5d70dbfd93c7006bd90a658c6179a95946/libs/langgraph/langgraph/graph/state.py)
  (MIT) model nodes, state channels, graph execution and checkpoint backends.
  BabyMind reuses its own much simpler DAG runner for bounded delegation; this
  team chat is not durable or resumable and does not use LangGraph.
- [Easy Agent agent tool](https://github.com/ConardLi/easy-agent/blob/2f8e7da20c5afee56c3b9e5f986941ca38718bbb/src/tools/agentTool.ts)
  (MIT) validates agent types and delegates to child loops with per-tool
  permissions and optional isolation. This review assumes the ConardLi project;
  the name is ambiguous. BabyMind's team passes have no child loops or tools.
- The name sandboxd is ambiguous: the [tastyeffectco app-builder manifest](https://github.com/tastyeffectco/sandboxd/blob/d02c63c1aa1d7008c76859940892089f797d0fdb/docs/sandbox-manifest.md)
  (MIT) describes managed app processes and previews; [inclusionAI sandbox file service](https://github.com/inclusionAI/sandboxd/blob/d23687d62ef0afd643b4028aedbcbc0e8bd346dc/internal/server/sandbox_files.go)
  (Apache-2.0) is part of a separate runtime daemon. Neither daemon is installed
  or treated as a security boundary here.
- [Mem0 memory implementation](https://github.com/mem0ai/mem0/blob/f1791daa86d469249c9b002f62644d58a1eb96a0/mem0/memory/main.py)
  (Apache-2.0) combines extraction, vector-store adapters, search and updates.
  BabyMind retains explicit, encrypted local memory and lexical retrieval; it
  does not import Mem0, vector embeddings or automatic fact extraction.
- [Hermes Agent subagent lifecycle](https://github.com/NousResearch/hermes-agent/blob/6b21d0564de0492e2ebd0d8f63fca86c03b5c892/agent/subagent_lifecycle.py)
  and [memory manager](https://github.com/NousResearch/hermes-agent/blob/6b21d0564de0492e2ebd0d8f63fca86c03b5c892/agent/memory_manager.py)
  (MIT) expose typed lifecycle states and memory-provider orchestration. The
  BabyMind slice reports role outcomes and preserves opt-in memory, but does
  not implement Hermes subagents, background lifecycle, skills or learning.

For prior source reviews of OpenHands, bolt.diy and GPT Researcher see the
preceding section. More complete compatibility, license and security review is
required before adopting any of these projects as a dependency.
