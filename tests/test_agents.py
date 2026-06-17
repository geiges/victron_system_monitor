from datetime import datetime, timedelta

from control.agents.system_safety import SystemSafetyAgent
from control.config import ControlConfig
from control.state import CurrentState
from control.projection import SystemProjection, ProjectedHour


def _make_projection(soc=0.50, voltage=25.0, temp=25.0):
    state = CurrentState(
        timestamp=datetime.now(),
        soc=soc,
        battery_voltage=voltage,
        battery_current=-5.0,
        battery_temp=temp,
        solar_power_w=100.0,
        ac_load_w=200.0,
    )
    return SystemProjection(
        current=state,
        forecast=None,
        horizon_hours=1,
        hours=[ProjectedHour(
            time=datetime.now() + timedelta(hours=1),
            solar_w=100.0,
            estimated_load_w=200.0,
            projected_soc=soc,
        )],
    )


# --- Normal state ---

def test_safety_no_action_when_all_ok():
    result = SystemSafetyAgent().run(_make_projection(), ControlConfig())
    assert result.actions == []
    assert "OK" in result.rationale


def test_safety_agent_name():
    result = SystemSafetyAgent().run(_make_projection(), ControlConfig())
    assert result.agent_name == "system_safety"


# --- Low SOC ---

def test_safety_low_soc_triggers_multiplus():
    result = SystemSafetyAgent().run(_make_projection(soc=0.10), ControlConfig())
    actuators = {a.actuator for a in result.actions}
    assert "multiplus_mode" in actuators
    assert "mppt100_load" not in actuators


def test_safety_low_soc_multiplus_set_to_off():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(_make_projection(soc=0.10), cfg)
    mp = next(a for a in result.actions if a.actuator == "multiplus_mode")
    assert mp.value == cfg.actuators.multiplus_mode_off


def test_safety_soc_exactly_at_limit_no_action():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(_make_projection(soc=cfg.battery.min_soc), cfg)
    assert result.actions == []


# --- Low voltage ---

def test_safety_low_voltage_triggers_multiplus():
    result = SystemSafetyAgent().run(_make_projection(voltage=22.0), ControlConfig())
    actuators = {a.actuator for a in result.actions}
    assert "multiplus_mode" in actuators
    assert "mppt100_load" not in actuators


def test_safety_voltage_exactly_at_limit_no_action():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(_make_projection(voltage=cfg.battery.min_voltage), cfg)
    assert result.actions == []


# --- Over temperature ---

def test_safety_high_temp_triggers_multiplus():
    result = SystemSafetyAgent().run(_make_projection(temp=46.0), ControlConfig())
    actuators = {a.actuator for a in result.actions}
    assert "multiplus_mode" in actuators


def test_safety_high_temp_no_duplicate_multiplus_action():
    """When both low SOC and high temp apply, multiplus_mode appears only once."""
    result = SystemSafetyAgent().run(_make_projection(soc=0.10, temp=46.0), ControlConfig())
    mp_actions = [a for a in result.actions if a.actuator == "multiplus_mode"]
    assert len(mp_actions) == 1


# --- Metrics ---

def test_safety_metrics_always_present():
    result = SystemSafetyAgent().run(_make_projection(), ControlConfig())
    assert "soc_margin" in result.metrics
    assert "voltage_margin" in result.metrics
    assert "temp_margin" in result.metrics


def test_safety_metrics_soc_margin_positive_when_ok():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(_make_projection(soc=0.50), cfg)
    assert result.metrics["soc_margin"] > 0


def test_safety_metrics_soc_margin_negative_when_low():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(_make_projection(soc=0.10), cfg)
    assert result.metrics["soc_margin"] < 0


# --- Rationale ---

def test_safety_rationale_mentions_soc_on_low_soc():
    result = SystemSafetyAgent().run(_make_projection(soc=0.05), ControlConfig())
    assert "SOC" in result.rationale


def test_safety_rationale_mentions_voltage_on_low_voltage():
    result = SystemSafetyAgent().run(_make_projection(voltage=20.0), ControlConfig())
    assert "voltage" in result.rationale.lower()


def test_safety_rationale_mentions_temp_on_overtemp():
    result = SystemSafetyAgent().run(_make_projection(temp=50.0), ControlConfig())
    assert "temperature" in result.rationale.lower()


# --- Actions are immediate ---

def test_safety_actions_are_due_immediately():
    result = SystemSafetyAgent().run(_make_projection(soc=0.10), ControlConfig())
    for action in result.actions:
        assert action.is_due(window_seconds=60.0)
