"""BabyMind has one persistent identity and one model-facing agent: BM-01."""
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
PHASES = ("planning", "research", "design", "architecture", "implementation", "verification", "review", "delivery", "acceptance")


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_id: str
    name: str
    domain: str
    purpose: str
    phase: str = "implementation"
    capabilities: tuple[str, ...] = ()
    evidence: str = "A recorded contribution with the file or command it reasoned about."


BABYMIND = AgentSpec(
    agent_id="BM-01",
    name="BabyMind",
    domain="core",
    purpose="One unified AI identity for conversation, self-modeling, learning, and user-approved independent goals.",
    phase="implementation",
    capabilities=tuple(CAPABILITIES),
    evidence="A grounded answer, verified local state change, or clearly stated limitation.",
)
AGENTS: tuple[AgentSpec, ...] = (BABYMIND,)
AGENT_BY_ID: dict[str, AgentSpec] = {"BM-01": BABYMIND}


def validate_registry(agents: tuple[AgentSpec, ...] = AGENTS) -> None:
    if len(agents) != 1 or agents[0].agent_id != "BM-01":
        raise ValueError("BabyMind must have exactly one identity: BM-01.")
    if len({agent.name for agent in agents}) != 1:
        raise ValueError("BabyMind identity must be unique.")
    for agent in agents:
        unknown = set(agent.capabilities) - set(CAPABILITIES)
        if unknown:
            raise ValueError(f"{agent.agent_id} declares unknown capabilities: {sorted(unknown)}.")
        if not agent.purpose.strip() or not agent.evidence.strip():
            raise ValueError("BabyMind identity requires a purpose and evidence policy.")


def can_use(agent_id: str, capability: str) -> bool:
    agent = AGENT_BY_ID.get(agent_id.strip().upper())
    return bool(agent and capability in agent.capabilities)


def require(capability: str, agent_id: str) -> AgentSpec:
    agent = AGENT_BY_ID.get(agent_id.strip().upper())
    if agent is None:
        raise PermissionError(f"Unknown identity: {agent_id}")
    if capability not in agent.capabilities:
        raise PermissionError(f"{agent.name} is not permitted to {capability}.")
    return agent


def agents_in_phase(phase: str) -> tuple[AgentSpec, ...]:
    return tuple(agent for agent in AGENTS if agent.phase == phase)


def agent_instructions(agent: AgentSpec) -> str:
    return (
        f"Identity: {agent.name} ({agent.agent_id}).\n"
        f"Purpose: {agent.purpose}\n"
        "Operate as one unified AI system, not as a team of simulated specialist agents. "
        "State assumptions, distinguish evidence from inference, and never claim tools, "
        "actions, feelings, or subjective consciousness that have not been established."
    )


validate_registry()
