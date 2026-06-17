import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ScheduledAction:
    execute_at: datetime
    actuator: str   # "multiplus_mode" or "mppt100_load"
    value: int      # D-Bus value to write
    reason: str
    agent: str

    def is_due(self, window_seconds: float = 30.0) -> bool:
        delta = (self.execute_at - datetime.now()).total_seconds()
        return -window_seconds <= delta <= window_seconds

    def to_dict(self) -> dict:
        return {
            "execute_at": self.execute_at.isoformat(),
            "actuator": self.actuator,
            "value": self.value,
            "reason": self.reason,
            "agent": self.agent,
        }


@dataclass
class Schedule:
    created_at: datetime
    actions: list   # list[ScheduledAction], sorted by execute_at

    def due_now(self, window_seconds: float = 30.0) -> list:
        return [a for a in self.actions if a.is_due(window_seconds)]

    def to_dict(self) -> dict:
        return {
            "created_at": self.created_at.isoformat(),
            "actions": [a.to_dict() for a in self.actions],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
