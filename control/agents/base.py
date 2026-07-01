from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentResult:
    agent_name: str
    actions: list       # list[ScheduledAction]
    rationale: str
    metrics: dict       # dict[str, float]
    sequences: list = field(default_factory=list)  # list[SequenceIntent]

    def to_dict(self) -> dict:
        return {
            "agent": self.agent_name,
            "rationale": self.rationale,
            "metrics": self.metrics,
            "actions": [a.to_dict() for a in self.actions],
            "sequences": [s.to_dict() for s in self.sequences],
        }


class BaseAgent(ABC):
    name: str = ""
    fast_cycle: bool = False  # True → runs at safety_interval; False → control_interval

    @abstractmethod
    def run(self, projection, config) -> AgentResult:
        """Analyse the system projection and return actions + rationale."""

    def is_enabled(self, config) -> bool:
        agent_cfg = getattr(config.agents, self.name, None)
        if agent_cfg is None:
            return True
        return bool(agent_cfg.enabled)
