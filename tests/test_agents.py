import csv
from datetime import datetime, timedelta
from pathlib import Path

from control.agents.system_safety import SystemSafetyAgent
from control.agents.soc_wallbox_charge import SocWallboxChargeAgent
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


# ---------------------------------------------------------------------------
# SocWallboxChargeAgent helpers
# ---------------------------------------------------------------------------

def _write_sim_csv(path, rows):
    """rows: list of (time: datetime, soc: float)"""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "SOC_counted", "SOC_Kf"])
        for t, soc in rows:
            writer.writerow([t.strftime("%H:%M:%S"), soc, soc])


def _wallbox_projection(soc=0.80):
    return _make_projection(soc=soc)


def _wallbox_cfg():
    cfg = ControlConfig()
    cfg.agents.soc_wallbox_charge.enabled = True
    cfg.agents.soc_wallbox_charge.soc_on_minutes = 30
    cfg.agents.soc_wallbox_charge.soc_on_threshold = 0.99
    cfg.agents.soc_wallbox_charge.soc_off_threshold = 0.25
    return cfg


# ---------------------------------------------------------------------------
# SocWallboxChargeAgent tests
# ---------------------------------------------------------------------------

def test_wallbox_agent_name():
    assert SocWallboxChargeAgent().name == "soc_wallbox_charge"


def test_wallbox_agent_fast_cycle():
    assert SocWallboxChargeAgent.fast_cycle is True


def test_wallbox_no_action_when_no_sim_files(tmp_path):
    # SOC must be at the full threshold so the agent tries to read sim files
    result = SocWallboxChargeAgent(tmp_path).run(_wallbox_projection(soc=1.0), _wallbox_cfg())
    assert result.actions == []
    assert "unavailable" in result.rationale.lower()


def test_wallbox_off_when_soc_below_threshold(tmp_path):
    # SOC below off threshold — wallbox should be turned off immediately
    result = SocWallboxChargeAgent(tmp_path).run(
        _wallbox_projection(soc=0.20), _wallbox_cfg()
    )
    actuators = {a.actuator for a in result.actions}
    assert "wallbox_charge" in actuators
    assert next(a for a in result.actions if a.actuator == "wallbox_charge").value == 0


def test_wallbox_off_action_is_immediate(tmp_path):
    result = SocWallboxChargeAgent(tmp_path).run(
        _wallbox_projection(soc=0.10), _wallbox_cfg()
    )
    for action in result.actions:
        assert action.is_due(window_seconds=60.0)


def test_wallbox_on_after_sufficient_time_at_full(tmp_path):
    # Create sim CSV: SOC at 1.0 for the past 40 minutes; last row ≈ now
    now = datetime.now()
    path = tmp_path / f"sim_{now.strftime('%y-%m-%d')}.csv"
    rows = [(now - timedelta(minutes=40 - i), 1.0) for i in range(41)]  # last row = now
    _write_sim_csv(path, rows)

    result = SocWallboxChargeAgent(tmp_path).run(_wallbox_projection(soc=1.0), _wallbox_cfg())
    actuators = {a.actuator for a in result.actions}
    assert "wallbox_charge" in actuators
    assert next(a for a in result.actions if a.actuator == "wallbox_charge").value == 1


def test_wallbox_waits_when_not_enough_time_at_full(tmp_path):
    # Create sim CSV: SOC at 1.0 for only 15 minutes; last row ≈ now
    now = datetime.now()
    path = tmp_path / f"sim_{now.strftime('%y-%m-%d')}.csv"
    rows = [(now - timedelta(minutes=15 - i), 1.0) for i in range(16)]  # last row = now
    _write_sim_csv(path, rows)

    result = SocWallboxChargeAgent(tmp_path).run(_wallbox_projection(soc=1.0), _wallbox_cfg())
    assert result.actions == []
    assert "waiting" in result.rationale.lower()


def test_wallbox_metrics_always_present(tmp_path):
    result = SocWallboxChargeAgent(tmp_path).run(_wallbox_projection(), _wallbox_cfg())
    assert "soc" in result.metrics


def test_wallbox_metrics_include_minutes_when_available(tmp_path):
    now = datetime.now()
    path = tmp_path / f"sim_{now.strftime('%y-%m-%d')}.csv"
    rows = [(now - timedelta(minutes=10 - i), 1.0) for i in range(11)]  # last row = now
    _write_sim_csv(path, rows)

    result = SocWallboxChargeAgent(tmp_path).run(_wallbox_projection(soc=1.0), _wallbox_cfg())
    assert "minutes_at_full" in result.metrics
    assert result.metrics["minutes_at_full"] is not None


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
