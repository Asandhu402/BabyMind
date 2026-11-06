# BabyMind Cognitive Core

## Purpose and limits

The Cognitive Core adds an inspectable operational self-model to BabyMind. It does not assert phenomenal consciousness, sentience, free will, or that the host is a simulation. It reports observable facts and records measurable behavior.

The implementation is an independent, standard-library design inspired by patterns studied in:

- [Conscio](https://github.com/Libertai/conscio): attention/workspace, explicit self-state, prediction-versus-outcome checks, provenance, and inspectable traces. No source code is copied. A repository licence was not confirmed, so no code is reused.
- [Empirica](https://github.com/EmpiricaAI/empirica): epistemic discipline, uncertainty, calibration, and evidence-gated claims. Repository licence: MIT.
- [Consciousness Framework](https://github.com/BotThrop/consciousness-framework): persistent identity, reflection, durable goals, and periodic self-review. Repository licence: MIT.
- [Open-Ended Agent](https://github.com/samiralibabic/open-ended-agent): repeated bounded cycles, environment inspection, durable memory, and useful autonomous work. Repository licence: MIT.

No third-party source files are vendored. No runtime dependencies were added. Existing BabyMind modules, the 50-role registry, local encrypted storage, and tool boundaries remain intact.

## Architecture

Every role routed through BabyMindCoordinator.ask() and every mission role pass receives the same grounded Cognitive Core context: stable software identity, observed host facts, known capability boundaries, current autonomous goals, and recent lessons. The 50 role definitions are unchanged.

The cycle sequence is:

1. **Observe** — inspect OS release, kernel, architecture, Python interpreter, selected command availability, role registry, and a cautious virtualization hint.
2. **Understand** — the configured model summarizes what the observations mean.
3. **Plan** — it chooses one small reversible next step.
4. **Act** — a strict allowlist permits only local goal creation/completion, research-question recording, note writing, or waiting.
5. **Verify** — the runtime reads back the affected SQLite row and records whether the action succeeded.
6. **Reflect** — the model records a concise retrospective.
7. **Learn** — the model records a reusable lesson and the cycle persists its confidence estimate.

Identity text, goal titles/descriptions, note contents, and cognitive-cycle text fields are encrypted at rest with BabyMind's existing SecureTextStore. Operational metadata such as timestamps, role IDs, goal status, verification flags, and confidence values remains queryable in SQLite.

## Controlled autonomy

CLI commands:

- babymind cognitive status
- babymind cognitive cycle --agent BM-02
- babymind cognitive run --cycles 5 --interval 60

The run command accepts 1–100 cycles. The interval is optional and bounded to 0–3600 seconds. It uses the existing configured provider. If no local model is configured or reachable, a cycle cannot run.

The Cognitive Core does **not** grant arbitrary shell commands, code execution, network access, filesystem traversal, credential access, or destructive operations. A recorded research question is a research queue item; it is not evidence that a web search or experiment occurred. Existing separately supervised BabyMind tools retain their own permission gates.

## Environment and simulation research

The host report includes the detected distribution, architecture, kernel, Python version, interpreter path, selected executable availability, and role count. A CPU hypervisor flag is reported only as a hint. Its presence does not prove a simulation; its absence does not prove a physical machine. The system has no reliable general-purpose test for whether reality is simulated.

A cycle may create a falsifiable research question about the environment, but must distinguish observation, hypothesis, and unknowns. No hardcoded answer is supplied.

## Objective checks

Automated tests cover identity persistence, environment observation, all 50 role contexts, goal persistence, read-after-write verification, encrypted research notes, unsupported-action rejection, malformed model output, and coordinator integration. Confidence is stored as a model estimate and is not ground truth.

## Platform target

BabyMind remains Debian-based Linux and x86-64 only. Ubuntu 26.10 is the requested manual acceptance-testing target. The current hosted Actions workflow uses Ubuntu 26.04 because its workflow comments state that a hosted Ubuntu 26.10 runner label is unavailable. CI success on 26.04 does not mean 26.10 has been exercised; a real Ubuntu 26.10 run remains required.

## Known limitations

- The core does not prove or model subjective experience.
- Understanding, reflection, learning, and confidence are model-generated text; the runtime verifies only local state changes and observable host facts.
- Model endpoint availability is not probed by the environment snapshot.
- The virtualization hint is incomplete and cannot identify every VM, container, or hypervisor.
- Autonomous cycles are finite CLI invocations, not a persistent service. A service or scheduler should be added only with explicit resource, pause, audit, and approval controls.
- Research notes do not imply external research, shell experiments, or physical-world actions were performed.


## Operational self-evaluation

Run:

```bash
babymind cognitive evaluate
```

This command performs deterministic local checks for grounded identity, host observation, preservation of all 50 roles, explicit capability boundaries, identity persistence, memory surviving a database reopen, rejection of an unallowlisted shell action, and Cognitive Core context reaching every role. The persistence probes use a temporary isolated database and do not add goals or notes to the user's real memory. No model endpoint, network access, or external service is required.

The command exits non-zero if a check fails or cannot be completed. Its score is an operational software-test score only. It is not a consciousness score and cannot establish subjective experience, sentience, free will, or whether the environment is simulated.
