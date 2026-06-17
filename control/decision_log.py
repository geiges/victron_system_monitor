import json
from datetime import datetime
from pathlib import Path


class DecisionLog:
    def __init__(self, path: Path):
        self._path = path

    def append(self, entry: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a") as f:
            f.write(json.dumps(entry) + "\n")

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
    projected_socs = [h.projected_soc for h in projection.hours]
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
            "soc_at_end": projected_socs[-1] if projected_socs else None,
            "min_soc": min(projected_socs) if projected_socs else None,
            "min_soc_hour": projected_socs.index(min(projected_socs)) + 1
                            if projected_socs else None,
        },
        "agents": [r.to_dict() for r in results],
        "schedule": [a.to_dict() for a in schedule.actions],
    }
