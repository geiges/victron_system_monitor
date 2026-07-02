"""In-memory sequence runner.

State lives entirely in Python objects inside run_loop(). A status JSON is
written after each tick for REST API display — it is never read back to drive
the sequence (no file-based tick state exchange).
"""
import json
import pytz
from datetime import datetime
from pathlib import Path
from typing import Optional

from control.sequence import Sequence, SequenceState, SequenceStep
from control.schedule import ScheduledAction


# Don't restart a successfully completed sequence within this window (in-session only).
_COOLDOWN_S = 300


class SequenceRunner:
    def __init__(self, status_path: Path, tz: str):
        self._status_path = status_path
        self._sequence: Optional[Sequence] = None
        self._steps: list[SequenceStep] = []
        self._state: Optional[SequenceState] = None
        self._cooldown: dict[str, datetime] = {}  # sequence_name → completed_at
        self.timezone = pytz.timezone(tz)


    def is_active(self) -> bool:
        return self._state is not None and self._state.status == "running"

    def start(self, sequence: Sequence, config, system_config_path: Path) -> bool:
        """Start a sequence. Returns False (no-op) if still in cooldown."""
        completed = self._cooldown.get(sequence.name)
        if completed is not None:
            elapsed = (datetime.now(tz=self.timezone) - completed).total_seconds()
            if elapsed < _COOLDOWN_S:
                print(f"[sequence] {sequence.name!r} completed {elapsed:.0f}s ago — cooldown active")
                return False

        self._steps = sequence.build_steps(config, system_config_path)
        self._sequence = sequence
        self._state = SequenceState(
            sequence_name=sequence.name,
            current_step=0,
            total_steps=len(self._steps),
            step_name=self._steps[0].name,
            step_names=[s.name for s in self._steps],
            started_at=datetime.now(tz=self.timezone).isoformat(),
            step_attempt=0,
            action_executed=False,
            status="running",
            log=[f"[{datetime.now(tz=self.timezone):%H:%M:%S}] started"],
        )
        self._write_status()
        print(f"[sequence] started {sequence.name!r} ({len(self._steps)} steps)")
        return True

    def tick(self, config, system_config_path: Path) -> list[ScheduledAction]:
        """Advance the sequence one tick (called every 10 s).

        Returns a list of ScheduledActions to execute via the normal actuator path.
        """
        if not self.is_active():
            return []

        state = self._state
        step = self._steps[state.current_step]
        ts = f"[{datetime.now(tz=self.timezone):%H:%M:%S}]"

        if not state.action_executed:
            state.action_executed = True
            if step.action_fn is not None:
                action = step.action_fn()
                state.log.append(f"{ts} {state.step_name}: action scheduled → {action.actuator}={action.value}")
                print(f"[sequence] {state.step_name}: action → {action.actuator}={action.value}")
                self._write_status()
                return [action]  # executed externally; verify on next tick

            # No actuator action for this step: verify immediately
        ok = step.verify()
        attempt_info = f"{state.step_attempt}/{step.max_retries}"
        state.log.append(f"{ts} {state.step_name}: verify {'OK' if ok else f'waiting ({attempt_info})'}")
        print(f"[sequence] {state.step_name}: verify {'OK' if ok else f'waiting ({attempt_info})'}")

        if ok:
            next_idx = state.current_step + 1
            if next_idx >= state.total_steps:
                state.status = "done"
                state.completed_at = datetime.now(tz=self.timezone).isoformat()
                state.log.append(f"{ts} sequence complete")
                print(f"[sequence] {state.sequence_name!r} DONE")
                self._cooldown[state.sequence_name] = datetime.now(tz=self.timezone)
            else:
                state.current_step = next_idx
                state.step_name = self._steps[next_idx].name
                state.step_attempt = 0
                state.action_executed = False
        else:
            state.step_attempt += 1
            if state.step_attempt > step.max_retries:
                state.status = "failed"
                state.completed_at = datetime.now(tz=self.timezone).isoformat()
                state.log.append(f"{ts} {state.step_name}: max retries exceeded — sequence failed")
                print(f"[sequence] {state.sequence_name!r} FAILED at {state.step_name!r}")
            else:
                state.action_executed = False  # re-execute action on next tick

        self._write_status()
        return []

    def abort(self) -> None:
        if self._state and self._state.status == "running":
            self._state.status = "failed"
            self._state.completed_at = datetime.now(tz=self.timezone).isoformat()
            self._state.log.append(f"[{datetime.now(tz=self.timezone):%H:%M:%S}] manually aborted")
            self._write_status()
        self._sequence = None
        self._steps = []

    def _write_status(self) -> None:
        if self._state is None:
            return
        try:
            self._status_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._status_path, "w") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as exc:
            print(f"[sequence] failed to write status: {exc}")
