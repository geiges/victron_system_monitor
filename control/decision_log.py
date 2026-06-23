import json
from datetime import datetime
from pathlib import Path


class DecisionLog:
    def __init__(self, path: Path):
        self._path = path

    def append(self, entry) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def append_agent_result(self, result, timestamp: str = None) -> None:
        entry = {
            "timestamp": timestamp or datetime.now().isoformat(timespec="seconds"),
            "agent": result.agent_name,
            "rationale": result.rationale,
            "metrics": result.metrics,
            "actions": [a.to_dict() for a in result.actions],
        }
        self.append(entry)

    def tail(self, n: int = 50) -> list:
        if not self._path.exists():
            return []
        with open(self._path) as f:
            lines = f.readlines()
        entries = []
        for line in lines[-n:]:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries


def build_log_entry(state, forecast, projection, results, schedule) -> dict:
    """Assemble a JSON-serializable dict from one control cycle."""
    projected_socs = [s.projected_soc for s in projection.steps]
    if projected_socs:
        t0 = projection.current.timestamp
        min_soc = min(projected_socs)
        max_soc = max(projected_socs)
        min_step = projection.steps[projected_socs.index(min_soc)]
        max_step = projection.steps[projected_socs.index(max_soc)]
        proj_summary = {
            "soc_at_end": projected_socs[-1],
            "min_soc": min_soc,
            "max_soc": max_soc,
            "min_soc_hour": round((min_step.time - t0).total_seconds() / 3600, 2),
            "max_soc_hour": round((max_step.time - t0).total_seconds() / 3600, 2),
        }
    else:
        proj_summary = {
            "soc_at_end": None, "min_soc": None, "max_soc": None,
            "min_soc_hour": None, "max_soc_hour": None,
        }

    return {
        "timestamp": datetime.now().isoformat(),
        "current": {
            "soc": state.soc,
            "battery_voltage": state.battery_voltage,
            "battery_current": state.battery_current,
            "battery_temp": state.battery_temp,
            "solar_power_w": state.solar_power_w,
            "ac_load_w": state.ac_load_w,
        },
        "forecast_available": forecast is not None,
        "projection": {
            "horizon_hours": projection.horizon_hours,
            "soc_now": state.soc,
            **proj_summary,
        },
        "agents": [r.to_dict() for r in results],
        "schedule": [a.to_dict() for a in schedule.actions],
    }
