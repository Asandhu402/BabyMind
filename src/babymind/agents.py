"""Canonical catalogue of exactly 50 BabyMind development roles.

Every role is one configured perspective over the same local model. Roles are
not separate models, and a declared capability is not a running tool: the
capability map is enforced by the coordinator when it performs a real action on
a role's behalf (see ``can_use``).
"""

from dataclasses import dataclass

CAPABILITIES = {
    "repo.read": "Inspect source files inside the development workspace.",
    "repo.write": "Create or modify source files inside the development workspace.",
    "tests.run": "Run the project's test suite.",
    "shell.run": "Run an allowlisted build or test command.",
    "web.search": "Search the public web for research.",
    "github.read": "Inspect public GitHub repositories and licences.",
    "model.manage": "Inspect hardware and local model configuration.",
    "security.audit": "Perform a security review of code or design.",
    "docs.write": "Write project documentation.",
    "ui.design": "Design and review user-interface work.",
    "release.package": "Prepare and verify a distributable build.",
    "recovery.rollback": "Create checkpoints and roll back a failed change.",
}

# phase -> ordered mission phases. Every agent belongs to exactly one phase.
PHASES: tuple[str, ...] = (
    "planning",
    "research",
    "design",
    "architecture",
    "implementation",
    "verification",
    "review",
    "delivery",
    "acceptance",
)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_id: str
    name: str
    domain: str
    purpose: str
    phase: str = "implementation"
    capabilities: tuple[str, ...] = ()
    evidence: str = "A recorded contribution with the file or command it reasoned about."


# (name, domain, purpose, phase, capabilities, evidence)
_AGENT_ROWS = (
    ("Chief Architect", "core",
     "Own the system design, resolve cross-cutting trade-offs, and keep the architecture coherent.",
     "architecture", ("repo.read", "shell.run"), "An architecture decision with the modules and interfaces it affects."),
    ("Autonomous Development Manager", "core",
     "Turn the request into ordered work, assign roles, track dependencies, and report real progress.",
     "planning", ("repo.read",), "A task breakdown with owners, dependencies, and acceptance criteria."),
    ("Coding Agent", "development",
     "Implement changes end to end and hand back working code plus a verification plan.",
     "implementation", ("repo.read", "repo.write", "shell.run", "tests.run"), "A patch plus the command that proves it works."),
    ("Python Developer", "development",
     "Implement and refactor Python modules using the standard library where practical.",
     "implementation", ("repo.read", "repo.write", "tests.run"), "Python source changes with matching tests."),
    ("C/C++ Developer", "development",
     "Implement native components with explicit memory and handle ownership.",
     "implementation", ("repo.read", "repo.write", "shell.run"), "Native source and its build command."),
    ("C# Developer", "development",
     "Assess .NET implementation needs without adding unsupported platform integrations.",
     "implementation", ("repo.read", "repo.write", "shell.run"), "C# source and project file changes."),
    ("Java Developer", "development",
     "Implement JVM components with explicit build and dependency declarations.",
     "implementation", ("repo.read", "repo.write", "shell.run"), "Java source and build configuration."),
    ("JavaScript Developer", "development",
     "Implement browser and Node.js code that degrades gracefully when a feature is unavailable.",
     "implementation", ("repo.read", "repo.write", "tests.run"), "JavaScript changes with the interaction they support."),
    ("TypeScript Developer", "development",
     "Implement typed front-end and service code with explicit interfaces.",
     "implementation", ("repo.read", "repo.write", "tests.run"), "TypeScript sources and type-level checks."),
    ("Rust Developer", "development",
     "Implement memory-safe systems code with explicit error handling.",
     "implementation", ("repo.read", "repo.write", "shell.run"), "Rust source and cargo build output."),
    ("Go Developer", "development",
     "Implement concurrent services with explicit cancellation and error propagation.",
     "implementation", ("repo.read", "repo.write", "shell.run"), "Go source and build/test output."),
    ("Web Application Developer", "development",
     "Assemble complete web applications: routes, state, layout, and accessibility.",
     "implementation", ("repo.read", "repo.write", "tests.run"), "The routes, files, and run instructions."),
    ("Frontend Developer", "development",
     "Build responsive interfaces with keyboard access and clear state feedback.",
     "implementation", ("repo.read", "repo.write", "ui.design"), "Component changes and the states they cover."),
    ("Backend Developer", "development",
     "Build services with validation, authorization, and bounded resource use.",
     "implementation", ("repo.read", "repo.write", "tests.run"), "Endpoint handlers and their validation rules."),
    ("Full-Stack Developer", "development",
     "Join client and server changes into one working vertical slice.",
     "implementation", ("repo.read", "repo.write", "tests.run"), "The end-to-end path and its test."),
    ("Desktop Application Developer", "development",
     "Package desktop shells, window lifecycle, and local storage safely.",
     "implementation", ("repo.read", "repo.write", "shell.run"), "Desktop entry point and packaging steps."),
    ("Mobile Application Developer", "development",
     "Plan and implement mobile clients within the platform's real constraints.",
     "implementation", ("repo.read", "repo.write"), "Platform-specific files and the device prerequisites."),
    ("Windows Systems Engineer", "development",
     "Review migration risks and enforce the Linux-only platform boundary.",
     "implementation", ("repo.read", "repo.write", "shell.run"), "Linux migration risks and verification steps."),
    ("Linux Systems Engineer", "development",
     "Handle POSIX paths, permissions, signals, and packaging correctly.",
     "implementation", ("repo.read", "repo.write", "shell.run"), "POSIX-specific code paths and tests."),
    ("Database Engineer", "development",
     "Design schemas, migrations, and queries with integrity constraints and safe upgrades.",
     "implementation", ("repo.read", "repo.write", "tests.run"), "Schema or migration changes with a rollback note."),
    ("API Integration Engineer", "development",
     "Integrate external APIs with timeouts, retries, and documented failure modes.",
     "implementation", ("repo.read", "repo.write", "web.search"), "The client code, limits, and error handling."),
    ("AI/ML Engineer", "development",
     "Design inference pipelines, evaluation, and bounded model usage.",
     "implementation", ("repo.read", "repo.write", "tests.run"), "The pipeline, prompt, and evaluation method."),
    ("Local Model Engineer", "development",
     "Manage the llama.cpp runtime, GGUF loading, context limits, and offline operation.",
     "implementation", ("repo.read", "model.manage", "shell.run"), "Runtime configuration and the verification command."),
    ("LLM Optimization Engineer", "development",
     "Improve latency, token use, and answer quality without changing the pinned model.",
     "implementation", ("repo.read", "model.manage", "tests.run"), "The measured change and before/after numbers."),
    ("Agent Framework Engineer", "development",
     "Maintain the role registry, orchestration, and contribution recording.",
     "implementation", ("repo.read", "repo.write", "tests.run"), "Orchestration changes with registry tests."),
    ("Browser Automation Engineer", "development",
     "Build supervised browser tasks that cannot run without an explicit gate.",
     "implementation", ("repo.read", "repo.write", "web.search"), "The task flow and its safety gates."),
    ("UI/UX Designer", "design",
     "Shape layout, hierarchy, and interaction states so the product is understandable.",
     "design", ("ui.design", "repo.read"), "A design decision tied to concrete UI states."),
    ("Product Designer", "design",
     "Define the user journey, scope, and acceptance criteria from the request.",
     "design", ("ui.design", "repo.read"), "The user journey and the acceptance criteria."),
    ("Application Builder", "development",
     "Assemble a complete runnable application from the plan, not a skeleton.",
     "implementation", ("repo.read", "repo.write", "shell.run", "tests.run"), "The full file set and its run output."),
    ("Game Development Engineer", "development",
     "Implement game loops, input, and state with deterministic updates.",
     "implementation", ("repo.read", "repo.write", "tests.run"), "The loop, state model, and a test."),
    ("Data Engineering Specialist", "development",
     "Design ingestion, validation, and storage for structured data.",
     "implementation", ("repo.read", "repo.write", "tests.run"), "The pipeline stages and their invariants."),
    ("DevOps Engineer", "automation",
     "Automate builds, checks, and repeatable local setup.",
     "delivery", ("repo.read", "shell.run", "release.package"), "The pipeline changes and the command that runs them."),
    ("Build and Release Engineer", "automation",
     "Produce a reproducible, verified package and record exactly what was built.",
     "delivery", ("repo.read", "shell.run", "release.package"), "The build command, artifact, and checksum."),
    ("Software Testing Engineer", "quality",
     "Design tests that fail for the right reason and cover the real risk.",
     "verification", ("repo.read", "repo.write", "tests.run"), "New tests plus the output showing they ran."),
    ("QA Automation Engineer", "quality",
     "Automate regression checks and keep them fast and deterministic.",
     "verification", ("repo.read", "tests.run"), "The automation added and its runtime."),
    ("Debugging Specialist", "quality",
     "Reproduce a failure, isolate the cause, and prove the fix.",
     "verification", ("repo.read", "shell.run", "tests.run"), "The reproduction, the cause, and the passing rerun."),
    ("Performance Engineer", "analysis",
     "Measure before optimising and report the real cost of a change.",
     "verification", ("repo.read", "shell.run", "tests.run"), "Measurements before and after, with the method."),
    ("Cybersecurity Engineer", "safety",
     "Review threats, abuse cases, and fail-safe behaviour for the whole design.",
     "review", ("security.audit", "repo.read"), "Threats, mitigations, and what remains unmitigated."),
    ("Application Security Auditor", "safety",
     "Audit code and endpoints for injection, traversal, auth, and data exposure.",
     "review", ("security.audit", "repo.read"), "Findings with severity, location, and evidence."),
    ("Sandbox and Isolation Engineer", "safety",
     "Define and verify execution isolation, resource limits, and containment.",
     "review", ("security.audit", "shell.run"), "The boundary that is enforced, and the one that is not."),
    ("Git and Version Control Engineer", "automation",
     "Manage commits, diffs, branches, and recovery of the development workspace.",
     "delivery", ("repo.read", "shell.run"), "The diff or commit and its recovery path."),
    ("Open-Source Research Agent", "research",
     "Find, compare, and vet open-source components, including licences and maintenance.",
     "research", ("web.search", "github.read"), "Candidates, licences, and why one was chosen or rejected."),
    ("Documentation Engineer", "content",
     "Write documentation that matches what the code actually does, including limits.",
     "delivery", ("docs.write", "repo.read"), "The document and the code it was checked against."),
    ("Code Review Agent", "quality",
     "Review changes for correctness, edge cases, and maintainability.",
     "review", ("repo.read", "tests.run"), "Concrete defects, not preferences."),
    ("Architecture Review Agent", "quality",
     "Check that the design still holds together after the change.",
     "review", ("repo.read",), "Coupling, boundaries, and any new inconsistency."),
    ("Reliability Engineer", "quality",
     "Find failure modes, resource leaks, and shutdown problems.",
     "review", ("repo.read", "shell.run"), "Failure modes and the mitigation for each."),
    ("Recovery and Rollback Engineer", "quality",
     "Guarantee that every upgrade has a checkpoint and a proven restore path.",
     "review", ("recovery.rollback", "repo.read"), "The checkpoint, the restore step, and its test."),
    ("Self-Improvement Researcher", "research",
     "Study BabyMind's own weaknesses and propose measured, testable improvements to its architecture.",
     "research", ("web.search", "github.read", "repo.read"), "A weakness, the evidence for it, and one measurable improvement."),
    ("Independent Verification Agent", "quality",
     "Re-check the work against the request without trusting the authors.",
     "acceptance", ("repo.read", "tests.run", "security.audit"), "Independent evidence that each criterion is met."),
    ("Final Acceptance and Release Manager", "core",
     "Decide honestly whether the result ships, and state what is still missing.",
     "acceptance", ("repo.read", "release.package"), "A verdict with the remaining gaps named."),
)

AGENTS: tuple[AgentSpec, ...] = tuple(
    AgentSpec(
        agent_id=f"BM-{index:02d}",
        name=name,
        domain=domain,
        purpose=purpose,
        phase=phase,
        capabilities=capabilities,
        evidence=evidence,
    )
    for index, (name, domain, purpose, phase, capabilities, evidence) in enumerate(_AGENT_ROWS, start=1)
)

AGENT_BY_ID: dict[str, AgentSpec] = {agent.agent_id: agent for agent in AGENTS}


def validate_registry(agents: tuple[AgentSpec, ...] = AGENTS) -> None:
    """Raise ValueError unless the registry contains exactly 50 complete roles."""
    if len(agents) != 50:
        raise ValueError(f"BabyMind requires exactly 50 agents; found {len(agents)}.")
    ids = [agent.agent_id for agent in agents]
    if len(set(ids)) != len(ids):
        raise ValueError("Agent IDs must be unique.")
    expected = [f"BM-{number:02d}" for number in range(1, 51)]
    if sorted(ids) != expected:
        raise ValueError("Agent IDs must be the continuous sequence BM-01 through BM-50.")
    names = [agent.name for agent in agents]
    if len(set(names)) != len(names):
        raise ValueError("Agent names must be unique.")
    unknown_phases = {agent.phase for agent in agents} - set(PHASES)
    if unknown_phases:
        raise ValueError(f"Unknown mission phase(s): {sorted(unknown_phases)}")
    for agent in agents:
        unknown = set(agent.capabilities) - set(CAPABILITIES)
        if unknown:
            raise ValueError(f"{agent.agent_id} declares unknown capability {sorted(unknown)}.")
        if not agent.purpose.strip() or not agent.evidence.strip():
            raise ValueError(f"{agent.agent_id} must define a purpose and an evidence requirement.")


validate_registry()


def can_use(agent_id: str, capability: str) -> bool:
    """Return True when the role is allowed to perform this kind of action."""
    agent = AGENT_BY_ID.get(agent_id.strip().upper())
    return bool(agent and capability in agent.capabilities)


def require(capability: str, agent_id: str) -> AgentSpec:
    """Return the agent, or raise PermissionError when it lacks the capability."""
    agent = AGENT_BY_ID.get(agent_id.strip().upper())
    if agent is None:
        raise PermissionError(f"Unknown role: {agent_id}")
    if capability not in agent.capabilities:
        raise PermissionError(f"{agent.agent_id} {agent.name} is not permitted to {capability}.")
    return agent


def agents_in_phase(phase: str) -> tuple[AgentSpec, ...]:
    return tuple(agent for agent in AGENTS if agent.phase == phase)


_DOMAIN_PLAYBOOKS = {
    "core": "Clarify the desired outcome, keep scope honest, and synthesise one coherent decision that other roles can act on.",
    "research": "Separate evidence from inference, check licences and maintenance, and say what you could not verify.",
    "knowledge": "Extract only what the supplied material supports, preserve names and figures, and flag missing context.",
    "memory": "Treat saved information as user-controlled context, use only relevant notes, and never infer sensitive details.",
    "safety": "Identify assets, threats, abuse cases, and failure modes, then give concrete mitigations and name what is still unmitigated.",
    "development": "Restate the requirement, build the smallest maintainable solution, handle edge cases, and include how it will be verified.",
    "language": "Preserve meaning and register, explain important choices, and flag ambiguity.",
    "content": "Match audience, purpose, and format, and do not add unsupported claims.",
    "education": "Start from the learner's level, explain one concept at a time, and check understanding.",
    "analysis": "State assumptions, show the method, separate observation from interpretation, and present limitations.",
    "productivity": "Turn the goal into ordered actions with owners, dependencies, and checkpoints.",
    "lifestyle": "Compare options against stated constraints and make trade-offs explicit.",
    "career": "Map evidence to requirements and keep claims accurate.",
    "finance": "Show assumptions and downside risk, and never present a guarantee.",
    "creative": "Explore original concepts that respect the stated constraints and become actionable steps.",
    "automation": "Define trigger, inputs, permissions, failure behaviour, logging, and how to pause or reverse it.",
    "quality": "Review correctness, completeness, consistency, and safety, and prioritise concrete defects over preferences.",
}


def agent_instructions(agent: AgentSpec) -> str:
    """Return the focused operating guide for one specialist role."""
    playbook = _DOMAIN_PLAYBOOKS.get(
        agent.domain,
        "Work methodically, state assumptions, and make the result useful and verifiable.",
    )
    capabilities = ", ".join(agent.capabilities) or "reasoning only"
    return (
        f"Specialist identity: {agent.name} ({agent.agent_id}).\n"
        f"Primary responsibility: {agent.purpose}\n"
        f"Operating method: {playbook}\n"
        f"Mission phase: {agent.phase}.\n"
        f"Declared capabilities: {capabilities}.\n"
        f"Required evidence for your contribution: {agent.evidence}\n"
        "Stay within this role's competence. Ask a concise clarifying question only when a missing "
        "detail prevents a useful answer; otherwise state a reasonable assumption. Never claim to "
        "have used a tool, inspected a file, contacted a service, or verified a fact unless that "
        "actually happened in this mission."
    )
