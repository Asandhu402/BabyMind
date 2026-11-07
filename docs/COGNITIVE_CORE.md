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

## Bounded autonomy, goal execution, and drift detection

Additional commands:

- `babymind cognitive autonomy --cycles 5 --interval 30` — run at most 25 bounded cognitive cycles.
- `babymind cognitive goal GOAL_ID --max-steps 5` — work toward one existing local goal for at most 10 steps; each step uses the Cognitive Core allowlist and read-after-write verification.
- `babymind cognitive benchmark` — run the operational capability benchmark and report scores by dimension.

The autonomy controller stores a compact encrypted baseline of observable host facts and compares later observations for changes in OS, distribution, kernel, architecture, Python interpreter, and BabyMind home paths. A change is reported as drift, not automatically treated as a fault. Failures are written to local notes when storage is available, so later cycles can inspect them. The separate default-on learning supervisor does not use drift as a fault signal; it runs verified source-improvement cycles under its own gates. See [permanent autonomous learning](AUTONOMOUS_LEARNING.md).

The action policy is fail-closed. The autonomous cognitive layer can only create or complete local goals, record research questions, write local notes, or wait. Shell execution, arbitrary code, network access, source edits, deletion, credentials, purchases, messages, and system changes are not enabled by this controller. Listing an operation as approval-required does not itself implement that operation; it must be handled by a separately supervised tool.

Goal execution is finite and goal-specific. The model receives the selected goal as an explicit objective, proposes one small step at a time, and the runtime verifies local state changes. If the goal remains active at the step limit, BabyMind reports that it is incomplete. The controller is a finite CLI process, not an always-on daemon; stopping the process stops autonomous work.

The benchmark score measures only the deterministic behaviors it exercises. It is not an IQ, general-intelligence, consciousness, or sentience score. A scripted provider verifies control-flow integration; only separate testing with the configured real model can assess the quality of its reasoning, and model outputs still require external evaluation.

## Objective checks

Automated tests cover identity persistence, environment observation, all 50 role contexts, goal persistence, read-after-write verification, encrypted research notes, unsupported-action rejection, malformed model output, and coordinator integration. Confidence is stored as a model estimate and is not ground truth.

## Platform target

BabyMind remains Debian-based Linux and x86-64 only. Ubuntu 26.10 is the requested manual acceptance-testing target. The current hosted Actions workflow uses Ubuntu 26.04 because its workflow comments state that a hosted Ubuntu 26.10 runner label is unavailable. CI success on 26.04 does not mean 26.10 has been exercised; a real Ubuntu 26.10 run remains required.

## Known limitations

- The core does not prove or model subjective experience.
- Understanding, reflection, learning, and confidence are model-generated text; the runtime verifies only local state changes and observable host facts.
- Model endpoint availability is not probed by the environment snapshot.
- The virtualization hint is incomplete and cannot identify every VM, container, or hypervisor.
- Cognitive Core's own autonomous cycles remain finite CLI invocations; its optional background service is separate and explicitly installed. BabyMind's default-on permanent learning supervisor is also separate: it has explicit resource bounds, pause/stop controls, a durable audit and verification gates, but it improves source through the verified learning cycle rather than running Cognitive Core goals. See [permanent autonomous learning](AUTONOMOUS_LEARNING.md).
- Research notes do not imply external research, shell experiments, or physical-world actions were performed.


## Operational self-evaluation

Run:

```bash
babymind cognitive evaluate
```

This command performs deterministic local checks for grounded identity, host observation, preservation of all 50 roles, explicit capability boundaries, identity persistence, memory surviving a database reopen, rejection of an unallowlisted shell action, a scripted autonomous cycle, reuse of prior reflection in the next planning context, and Cognitive Core context reaching every role. The persistence probes use a temporary isolated database and do not add goals or notes to the user's real memory. No model endpoint, network access, or external service is required.

The scripted cycle check validates that a future planning call receives a prior reflection; it does not measure the quality of a real model's reasoning. The command exits non-zero if a check fails or cannot be completed. Its score is an operational software-test score only. It is not a consciousness score and cannot establish subjective experience, sentience, free will, or whether the environment is simulated.


## Persistent background service

The optional Linux user service runs BabyMind's existing bounded cognitive cycle
continuously between explicit stop requests. Install it after installing BabyMind:

```bash
bash scripts/install-cognitive-service.sh
systemctl --user status babymind-cognitive.service
systemctl --user disable --now babymind-cognitive.service
```

The service uses a per-installation file lock to prevent duplicate instances,
waits at least five seconds between cycles, handles SIGTERM/SIGINT, records
recoverable errors, backs off exponentially, and stops after five consecutive
failures. It runs as the logged-in user, not root. It does not expand the
Cognitive Core action allowlist. It is a persistent process, not proof of
subjective awareness. Logs are available through
`journalctl --user -u babymind-cognitive.service`.

For foreground debugging, run
`babymind cognitive service --interval 60 --agent BM-02` and stop with Ctrl+C.

This optional cognitive service is **not** the default-on learning service.
`install-linux.sh` also installs `babymind-learning.service` when a systemd user
session is available. It runs the headless `--learning-service` launcher, holds
distinct cycle and supervisor locks, and remains idle while a desktop session
owns the in-app learning supervisor. Both services are bounded, run as the user
and have explicit stop controls; neither is a claim of subjective awareness.
See [permanent autonomous learning](AUTONOMOUS_LEARNING.md).

## Independent specialist model routing

The 50 role definitions remain intact. By default, all roles continue to use
the configured BabyMind provider. To route individual roles or domains to
different OpenAI-compatible model endpoints, set
`BABYMIND_AGENT_MODEL_MAP` to a JSON object. A route key may be a role ID
(such as `BM-03`), a role domain (such as `development`), or `*` for a
fallback route. Role IDs take precedence over domains, which take precedence
over `*`. Example:

```json
{
  "BM-03": {"base_url": "http://127.0.0.1:9001/v1", "model": "coder-model"},
  "research": {"base_url": "http://127.0.0.1:9002/v1", "model": "research-model"},
  "*": {"base_url": "http://127.0.0.1:9003/v1", "model": "general-model"}
}
```

Endpoints must use HTTPS or loopback HTTP. API keys are never placed in the
JSON map; use `api_key_env` to name an environment variable containing the
secret. Unmapped roles use the configured shared provider. Each configured
route is lazily initialized and cached. This makes independent model selection
possible without pretending that 50 roles are 50 separate models. It does not
download models or guarantee that multiple local models fit in available RAM.
Inspect routing with `babymind cognitive routing`; secrets are not displayed.


## Routing across missions and the background service

Per-role routing is used by direct specialist conversations, cognitive cycles,
and all 50 role passes in both CLI and web missions. Self-edit proposal
generation is routed through the coding specialist (BM-03). The existing
shared provider remains the fallback for roles without a specific route.

The systemd installer creates `~/.config/babymind/models.env` with mode 0600
and adds it as an optional EnvironmentFile. Put `BABYMIND_AGENT_MODEL_MAP='{"BM-03":{"base_url":"http://127.0.0.1:9001/v1","model":"coder"}}'`
there to configure a role-specific local model for the background service.
Keep any API key in a separate environment assignment whose value is not
committed to source control. Restart the service after changing the file.
