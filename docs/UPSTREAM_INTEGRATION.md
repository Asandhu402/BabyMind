# Upstream integration research

`src/babymind/integrations/upstream_components.py` records Linux-relevant
references. These entries and the optional uninitialized Git submodules are
research material, not enabled integrations or trusted dependencies. Do not
execute imported code automatically. Review a specific commit, source, licenses,
dependencies and security behavior before adopting any project; maintain
attribution and test it on the actual Linux target. No cloud model service,
Docker installation or paid account is required by the core app.

The namespace sandbox is not a workspace authorization broker. A source-mode
`auto` policy can fall back to uncontained execution; use `require` for
untrusted commands. Generated code from the app builder is not sandboxed. See
[security policy](../SECURITY.md) and [limitations](KNOWN_LIMITATIONS.md).

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
