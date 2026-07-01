from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from control.schedule import ScheduledAction


@dataclass
class SequenceStep:
    name: str
    # Returns the ScheduledAction to execute, or None if step has no actuator action.
    action_fn: Optional[Callable[[], ScheduledAction]]
    verify: Callable[[], bool]
    max_retries: int = 5


@dataclass
class SequenceState:
    """In-memory state; written to a status file for REST API display only."""
    sequence_name: str
    current_step: int
    total_steps: int
    step_name: str
    started_at: str       # ISO 8601
    step_attempt: int
    action_executed: bool
    status: str           # "running" | "done" | "failed"
    step_names: list = field(default_factory=list)  # all step names in order, for API/dashboard display
    log: list = field(default_factory=list)
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "sequence_name": self.sequence_name,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "step_name": self.step_name,
            "step_names": self.step_names,
            "started_at": self.started_at,
            "step_attempt": self.step_attempt,
            "action_executed": self.action_executed,
            "status": self.status,
            "log": self.log,
            "completed_at": self.completed_at,
        }


@dataclass
class SequenceIntent:
    """Emitted by an agent to request a named sequence."""
    sequence_name: str
    execute_at: datetime
    agent: str
    reason: str

    def is_due(self, window_seconds: float = 30.0) -> bool:
        delta = (self.execute_at - datetime.now()).total_seconds()
        return -window_seconds <= delta <= window_seconds

    def to_dict(self) -> dict:
        return {
            "sequence_name": self.sequence_name,
            "execute_at": self.execute_at.isoformat(),
            "agent": self.agent,
            "reason": self.reason,
        }


class Sequence(ABC):
    name: str

    @abstractmethod
    def build_steps(self, config, system_config_path: Path) -> list[SequenceStep]:
        """Build steps as closures over config. Called once when the sequence starts."""
