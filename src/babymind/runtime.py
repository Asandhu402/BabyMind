"""Minimal dispatcher for the BabyMind agent catalogue."""

from dataclasses import dataclass

from .agents import AGENTS, AgentSpec, validate_registry


@dataclass(frozen=True, slots=True)
class AgentResult:
    agent_id: str
    agent_name: str
    task: str
    status: str
    message: str


class BabyMindRuntime:
    def __init__(self, agents: tuple[AgentSpec, ...] = AGENTS) -> None:
        validate_registry(agents)
        self._agents = {agent.agent_id: agent for agent in agents}

    @property
    def agents(self) -> tuple[AgentSpec, ...]:
        return tuple(self._agents.values())

    def run(self, agent_id: str, task: str) -> AgentResult:
        normalized_id = agent_id.strip().upper()
        clean_task = task.strip()
        if not clean_task:
            raise ValueError("Task must not be empty.")
        try:
            agent = self._agents[normalized_id]
        except KeyError as exc:
            raise KeyError(f"Unknown agent ID: {normalized_id}") from exc
        return AgentResult(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            task=clean_task,
            status="scaffold",
            message=(
                f"{agent.name} accepted the task. This role is registered and routable; "
                "connect a model/tool backend to enable full execution."
            ),
        )

    def health(self) -> dict[str, object]:
        return {
            "application": "BabyMind",
            "status": "ok",
            "agent_count": len(self._agents),
            "agent_ids_valid": True,
        }
