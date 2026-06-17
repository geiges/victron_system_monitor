import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from control.decision_log import DecisionLog, build_log_entry
from control.schedule import Schedule, ScheduledAction
from control.agents.base import AgentResult
from control.state import CurrentState
from control.forecast import SolarForecast, HourlyEntry
from control.projection import SystemProjection, ProjectedHour


_NOW = datetime(2026, 6, 17, 20, 0, 0)


def _make_state():
    return CurrentState(
        timestamp=_NOW,
        soc=0.72,
        battery_voltage=25.4,
        battery_current=-3.2,
        battery_temp=28.0,
        solar_power_w=45.0,
        ac_load_w=380.0,
    )


def _make_projection(soc_values):
    state = _make_state()
    hours = [
        ProjectedHour(
            time=_NOW + timedelta(hours=i + 1),
            solar_w=0.0,
            estimated_load_w=200.0,
            projected_soc=soc,
        )
        for i, soc in enumerate(soc_values)
    ]
    return SystemProjection(
        current=state, forecast=None, horizon_hours=len(hours), hours=hours
    )


def _make_schedule(actions=None):
    return Schedule(created_at=_NOW, actions=actions or [])


# --- DecisionLog ---

def test_append_creates_file(tmp_path):
    log = DecisionLog(tmp_path / "control_log.jsonl")
    log.append({"foo": "bar"})
    assert (tmp_path / "control_log.jsonl").exists()


def test_append_writes_valid_jsonl(tmp_path):
    log = DecisionLog(tmp_path / "control_log.jsonl")
    log.append({"a": 1})
    log.append({"b": 2})
    lines = (tmp_path / "control_log.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"a": 1}
    assert json.loads(lines[1]) == {"b": 2}


def test_tail_returns_last_n(tmp_path):
    log = DecisionLog(tmp_path / "control_log.jsonl")
    for i in range(10):
        log.append({"i": i})
    result = log.tail(3)
    assert len(result) == 3
    assert result[-1]["i"] == 9


def test_tail_empty_file(tmp_path):
    log = DecisionLog(tmp_path / "missing.jsonl")
    assert log.tail() == []


# --- build_log_entry ---

def test_build_log_entry_structure(tmp_path):
    state = _make_state()
    projection = _make_projection([0.70, 0.65, 0.55, 0.45, 0.30])
    results = [
        AgentResult("system_safety", [], "SOC ok", {"soc_margin": 0.57}),
    ]
    schedule = _make_schedule()

    entry = build_log_entry(state, None, projection, results, schedule)

    assert entry["current"]["soc"] == pytest.approx(0.72)
    assert entry["forecast_available"] is False
    assert entry["projection"]["soc_at_end"] == pytest.approx(0.30)
    assert entry["projection"]["min_soc"] == pytest.approx(0.30)
    assert entry["projection"]["min_soc_hour"] == 5
    assert len(entry["agents"]) == 1
    assert entry["agents"][0]["agent"] == "system_safety"


def test_build_log_entry_with_forecast(tmp_path):
    state = _make_state()
    projection = _make_projection([0.8])
    forecast = SolarForecast(fetched_at=_NOW, entries=[])
    entry = build_log_entry(state, forecast, projection, [], _make_schedule())
    assert entry["forecast_available"] is True


# --- Schedule and ScheduledAction ---

def test_scheduled_action_to_dict():
    action = ScheduledAction(
        execute_at=_NOW,
        actuator="multiplus_mode",
        value=4,
        reason="low SOC",
        agent="system_safety",
    )
    d = action.to_dict()
    assert d["actuator"] == "multiplus_mode"
    assert d["value"] == 4
    assert d["execute_at"] == _NOW.isoformat()


def test_schedule_save_and_reload(tmp_path):
    action = ScheduledAction(
        execute_at=_NOW,
        actuator="multiplus_mode",
        value=3,
        reason="test",
        agent="time_based",
    )
    schedule = Schedule(created_at=_NOW, actions=[action])
    path = tmp_path / "schedule.json"
    schedule.save(path)

    loaded = json.loads(path.read_text())
    assert loaded["actions"][0]["actuator"] == "multiplus_mode"
    assert loaded["actions"][0]["value"] == 3


# --- Arbitration (via runner logic) ---

def test_arbitration_safety_overrides_other(tmp_path):
    from control_runner import _arbitrate

    safety_action = ScheduledAction(
        execute_at=_NOW, actuator="multiplus_mode", value=4,
        reason="low SOC", agent="system_safety",
    )
    planning_action = ScheduledAction(
        execute_at=_NOW, actuator="multiplus_mode", value=3,
        reason="night mode", agent="time_based",
    )
    results = [
        AgentResult("system_safety", [safety_action], "SOC low", {}),
        AgentResult("time_based", [planning_action], "sunset", {}),
    ]
    schedule = _arbitrate(results)

    actuator_values = {a.actuator: a.value for a in schedule.actions}
    assert actuator_values["multiplus_mode"] == 4  # safety wins


def test_arbitration_non_conflicting_actions_kept(tmp_path):
    from control_runner import _arbitrate

    safety_action = ScheduledAction(
        execute_at=_NOW, actuator="multiplus_mode", value=4,
        reason="low SOC", agent="system_safety",
    )
    other_action = ScheduledAction(
        execute_at=_NOW, actuator="mppt100_load", value=0,
        reason="reduce load", agent="time_based",
    )
    results = [
        AgentResult("system_safety", [safety_action], "SOC low", {}),
        AgentResult("time_based", [other_action], "night", {}),
    ]
    schedule = _arbitrate(results)
    assert len(schedule.actions) == 2
