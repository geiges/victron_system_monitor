import csv
import json
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Optional


class StateUnavailableError(Exception):
    pass


@dataclass
class CurrentState:
    timestamp: datetime
    soc: float              # Kalman-filtered SOC (0–1)
    battery_voltage: float  # V
    battery_current: float  # A (positive = charging)
    battery_temp: float     # °C
    solar_power_w: float    # W, sum of all MPPT yields
    ac_load_w: float        # W, multiplus AC output
    inverter_mode: Optional[int] = None   # D-Bus value: 3=on, 4=inverter-only
    mppt100_load_on: Optional[bool] = None


def _parse_time_field(time_str: str) -> datetime:
    """Combine today's date with the HH:MM:SS time from state.json."""
    t = datetime.strptime(time_str, "%H:%M:%S")
    today = date.today()
    return datetime(today.year, today.month, today.day, t.hour, t.minute, t.second)


def _solar_power_from_state(state: dict) -> float:
    """Sum solar power from state dict. Prefers the pre-summed system key."""
    if "system/power_yield" in state:
        return float(state["system/power_yield"])
    total = 0.0
    for key, val in state.items():
        if not key.startswith("system") and key.endswith("power_yield"):
            total += float(val)
    return total


def _read_last_soc_from_sim(data_dir: Path) -> Optional[float]:
    """Read SOC_Kf from the last row of the most recent sim CSV."""
    sim_files = sorted(data_dir.glob("sim_*.csv"))
    if not sim_files:
        return None
    with open(sim_files[-1], newline="") as f:
        reader = csv.DictReader(f)
        last_row = None
        for last_row in reader:
            pass
    if last_row is None or "SOC_Kf" not in last_row:
        return None
    try:
        return float(last_row["SOC_Kf"])
    except (ValueError, TypeError):
        return None


def read_current_state(data_dir: Path = Path("data")) -> CurrentState:
    state_file = data_dir / "state.json"
    if not state_file.exists():
        raise StateUnavailableError(f"state.json not found at {state_file}")

    with open(state_file) as f:
        state = json.load(f)

    # SOC: prefer coulomb-counted value; Kalman estimate is the fallback
    soc: Optional[float] = None
    for key in ("SOC_counted", "SOC_Kf"):
        if key in state:
            try:
                soc = float(state[key])
                break
            except (ValueError, TypeError):
                pass
    if soc is None:
        soc = _read_last_soc_from_sim(data_dir)
    if soc is None:
        raise StateUnavailableError(
            "SOC not available in state.json or sim CSV. "
            "Is dbus_logger.py running with simulate_system=True?"
        )

    required = {
        "system/battery_voltage": "battery_voltage",
        "system/battery_current": "battery_current",
    }
    missing = [k for k in required if k not in state]
    if missing:
        raise StateUnavailableError(
            f"Required fields missing from state.json: {missing}. "
            "Is dbus_logger.py running?"
        )

    timestamp = (
        _parse_time_field(state["time"]) if "time" in state else datetime.now()
    )

    return CurrentState(
        timestamp=timestamp,
        soc=soc,
        battery_voltage=float(state["system/battery_voltage"]),
        battery_current=float(state["system/battery_current"]),
        battery_temp=float(state.get("system/battery_temperature", 25.0)),
        solar_power_w=_solar_power_from_state(state),
        ac_load_w=float(state.get("multiplus/AC_power_output", 0.0)),
    )
