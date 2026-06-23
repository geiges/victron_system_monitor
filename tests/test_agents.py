import csv
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from control.agents.system_safety import SystemSafetyAgent
from control.agents.soc_wallbox_charge import SocWallboxChargeAgent
from control.agents.forecast_wallbox import ForecastWallboxAgent, _plan_windows
from control.config import ControlConfig
from control.forecast import SolarForecast, HourlyEntry
from control.state import CurrentState
from control.projection import SystemProjection, ProjectedStep, STEP_MINUTES


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
        steps=[ProjectedStep(
            time=datetime.now() + timedelta(minutes=15),
            solar_w=100.0,
            estimated_load_w=200.0,
            projected_soc=soc,
        )],
    )


# ---------------------------------------------------------------------------
# SystemSafetyAgent — enabled/disabled logic
# ---------------------------------------------------------------------------

def test_safety_is_enabled_by_default():
    assert SystemSafetyAgent().is_enabled(ControlConfig()) is True


def test_safety_not_disabled_by_enabled_flag_alone():
    cfg = ControlConfig()
    cfg.agents.system_safety.enabled = False
    assert SystemSafetyAgent().is_enabled(cfg) is True


def test_safety_disabled_with_both_flags():
    cfg = ControlConfig()
    cfg.agents.system_safety.enabled = False
    cfg.agents.system_safety.confirmed_disable = True
    assert SystemSafetyAgent().is_enabled(cfg) is False


def test_safety_confirmed_disable_alone_does_not_disable():
    cfg = ControlConfig()
    cfg.agents.system_safety.confirmed_disable = True
    assert SystemSafetyAgent().is_enabled(cfg) is True


# ---------------------------------------------------------------------------
# SystemSafetyAgent — normal state
# ---------------------------------------------------------------------------

def test_safety_no_action_when_all_ok():
    result = SystemSafetyAgent().run(_make_projection(), ControlConfig())
    assert result.actions == []
    assert "OK" in result.rationale


def test_safety_agent_name():
    result = SystemSafetyAgent().run(_make_projection(), ControlConfig())
    assert result.agent_name == "system_safety"


# ---------------------------------------------------------------------------
# SystemSafetyAgent — low SOC
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# SystemSafetyAgent — low voltage
# ---------------------------------------------------------------------------

def test_safety_low_voltage_triggers_multiplus():
    result = SystemSafetyAgent().run(_make_projection(voltage=22.0), ControlConfig())
    actuators = {a.actuator for a in result.actions}
    assert "multiplus_mode" in actuators
    assert "mppt100_load" not in actuators


def test_safety_voltage_exactly_at_min_limit_no_action():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(_make_projection(voltage=cfg.battery.min_voltage), cfg)
    assert result.actions == []


# ---------------------------------------------------------------------------
# SystemSafetyAgent — over/under voltage (new upper bound)
# ---------------------------------------------------------------------------

def test_safety_high_voltage_triggers_multiplus():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(
        _make_projection(voltage=cfg.battery.max_voltage + 0.5), cfg
    )
    assert any(a.actuator == "multiplus_mode" for a in result.actions)


def test_safety_voltage_exactly_at_max_limit_no_action():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(_make_projection(voltage=cfg.battery.max_voltage), cfg)
    assert result.actions == []


# ---------------------------------------------------------------------------
# SystemSafetyAgent — temperature
# ---------------------------------------------------------------------------

def test_safety_high_temp_triggers_multiplus():
    result = SystemSafetyAgent().run(_make_projection(temp=46.0), ControlConfig())
    actuators = {a.actuator for a in result.actions}
    assert "multiplus_mode" in actuators


def test_safety_low_temp_triggers_multiplus():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(
        _make_projection(temp=cfg.battery.min_temp - 1.0), cfg
    )
    assert any(a.actuator == "multiplus_mode" for a in result.actions)


def test_safety_high_temp_no_duplicate_multiplus_action():
    """When both low SOC and high temp apply, multiplus_mode appears only once."""
    result = SystemSafetyAgent().run(_make_projection(soc=0.10, temp=46.0), ControlConfig())
    mp_actions = [a for a in result.actions if a.actuator == "multiplus_mode"]
    assert len(mp_actions) == 1


# ---------------------------------------------------------------------------
# SystemSafetyAgent — multiple triggers: reason covers all
# ---------------------------------------------------------------------------

def test_safety_multiple_triggers_all_mentioned_in_rationale():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(
        _make_projection(soc=0.05, voltage=cfg.battery.min_voltage - 1, temp=50.0), cfg
    )
    assert "SOC" in result.rationale
    assert "voltage" in result.rationale.lower()
    assert "temperature" in result.rationale.lower()


# ---------------------------------------------------------------------------
# SystemSafetyAgent — metrics
# ---------------------------------------------------------------------------

def test_safety_metrics_always_present():
    result = SystemSafetyAgent().run(_make_projection(), ControlConfig())
    for key in ("soc_margin", "min_voltage_margin", "max_voltage_margin",
                "min_temp_margin", "max_temp_margin"):
        assert key in result.metrics


def test_safety_metrics_margins_positive_when_ok():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(_make_projection(soc=0.50, voltage=26.0, temp=25.0), cfg)
    assert result.metrics["soc_margin"] > 0
    assert result.metrics["min_voltage_margin"] > 0
    assert result.metrics["max_voltage_margin"] > 0
    assert result.metrics["min_temp_margin"] > 0
    assert result.metrics["max_temp_margin"] > 0


def test_safety_metrics_soc_margin_negative_when_low():
    cfg = ControlConfig()
    result = SystemSafetyAgent().run(_make_projection(soc=0.10), cfg)
    assert result.metrics["soc_margin"] < 0


# ---------------------------------------------------------------------------
# SystemSafetyAgent — actions are immediate
# ---------------------------------------------------------------------------

def test_safety_actions_are_due_immediately():
    result = SystemSafetyAgent().run(_make_projection(soc=0.10), ControlConfig())
    for action in result.actions:
        assert action.is_due(window_seconds=60.0)


# ---------------------------------------------------------------------------
# SystemSafetyAgent — rationale
# ---------------------------------------------------------------------------

def test_safety_rationale_mentions_soc_on_low_soc():
    result = SystemSafetyAgent().run(_make_projection(soc=0.05), ControlConfig())
    assert "SOC" in result.rationale


def test_safety_rationale_mentions_voltage_on_low_voltage():
    result = SystemSafetyAgent().run(_make_projection(voltage=20.0), ControlConfig())
    assert "voltage" in result.rationale.lower()


def test_safety_rationale_mentions_temp_on_overtemp():
    result = SystemSafetyAgent().run(_make_projection(temp=50.0), ControlConfig())
    assert "temperature" in result.rationale.lower()


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
    result = SocWallboxChargeAgent(tmp_path).run(_wallbox_projection(soc=1.0), _wallbox_cfg())
    assert result.actions == []
    assert "unavailable" in result.rationale.lower()


def test_wallbox_off_when_soc_below_threshold(tmp_path):
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
    now = datetime.now()
    path = tmp_path / f"sim_{now.strftime('%y-%m-%d')}.csv"
    rows = [(now - timedelta(minutes=40 - i), 1.0) for i in range(41)]
    _write_sim_csv(path, rows)

    result = SocWallboxChargeAgent(tmp_path).run(_wallbox_projection(soc=1.0), _wallbox_cfg())
    actuators = {a.actuator for a in result.actions}
    assert "wallbox_charge" in actuators
    assert next(a for a in result.actions if a.actuator == "wallbox_charge").value == 1


def test_wallbox_waits_when_not_enough_time_at_full(tmp_path):
    now = datetime.now()
    path = tmp_path / f"sim_{now.strftime('%y-%m-%d')}.csv"
    rows = [(now - timedelta(minutes=15 - i), 1.0) for i in range(16)]
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
    rows = [(now - timedelta(minutes=10 - i), 1.0) for i in range(11)]
    _write_sim_csv(path, rows)

    result = SocWallboxChargeAgent(tmp_path).run(_wallbox_projection(soc=1.0), _wallbox_cfg())
    assert "minutes_at_full" in result.metrics
    assert result.metrics["minutes_at_full"] is not None


# ---------------------------------------------------------------------------
# ForecastWallboxAgent — helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 6, 23, 8, 0, 0)   # 08:00 — already on a 15-min boundary


def _make_steps(solar_values: list[float], soc: float = 0.70) -> list:
    """Build ProjectedStep list with one step per entry in solar_values."""
    return [
        ProjectedStep(
            time=_T0 + timedelta(minutes=i * STEP_MINUTES),
            solar_w=w,
            estimated_load_w=20.0,
            projected_soc=soc,
        )
        for i, w in enumerate(solar_values)
    ]


def _make_forecast(solar_w: float = 2000.0) -> SolarForecast:
    """Constant solar forecast for the next 50 hours."""
    entries = [
        HourlyEntry(
            time=_T0 + timedelta(hours=h),
            mppt150_w=solar_w,
            mppt100_w=0.0,
        )
        for h in range(50)
    ]
    return SolarForecast(fetched_at=_T0, entries=entries)


def _fw_projection(steps, forecast=None, solar_now=2000.0) -> SystemProjection:
    state = CurrentState(
        timestamp=_T0,
        soc=0.70,
        battery_voltage=25.4,
        battery_current=0.0,
        battery_temp=25.0,
        solar_power_w=solar_now,
        ac_load_w=20.0,
    )
    if forecast is None:
        forecast = _make_forecast(solar_now)
    return SystemProjection(
        current=state,
        forecast=forecast,
        horizon_hours=48,
        steps=steps,
    )


def _fw_cfg(
    wallbox_power_w=1600.0,
    min_solar_fraction=0.5,
    min_period_minutes=30,
    merge_gap_minutes=30,
    max_periods_per_day=2,
) -> ControlConfig:
    cfg = ControlConfig()
    cfg.agents.forecast_wallbox.enabled = True
    cfg.agents.forecast_wallbox.wallbox_power_w = wallbox_power_w
    cfg.agents.forecast_wallbox.min_solar_fraction = min_solar_fraction
    cfg.agents.forecast_wallbox.min_period_minutes = min_period_minutes
    cfg.agents.forecast_wallbox.merge_gap_minutes = merge_gap_minutes
    cfg.agents.forecast_wallbox.max_periods_per_day = max_periods_per_day
    cfg.estimated_load_w = 20.0
    return cfg


def _plan(steps, **kw):
    """Call _plan_windows with sensible defaults, overridable via kw."""
    defaults = dict(
        base_load_w=20.0,
        wallbox_w=1600.0,
        efficiency=0.93,
        max_per_day=2,
        min_period_steps=2,   # 30 min = 2 steps
        merge_gap_steps=2,    # 30 min = 2 steps
        min_solar_fraction=0.5,
        min_soc=0.20,
        min_soc_buffer=0.05,
        bias_ratio=1.0,
        bias_steps=8,
    )
    defaults.update(kw)
    return _plan_windows(steps=steps, **defaults)


# ---------------------------------------------------------------------------
# _plan_windows — unit tests
# ---------------------------------------------------------------------------

def test_plan_windows_no_windows_when_no_solar():
    steps = _make_steps([0.0] * 96)   # full day, no solar
    assert _plan(steps) == []


def test_plan_windows_no_windows_when_solar_below_threshold():
    # wallbox_dc_w = 1600/0.93 ≈ 1720W, need surplus >= 860W for 50% coverage
    # base_load=20, so solar needs to be >= 880W; use 500W (well below)
    steps = _make_steps([500.0] * 96)
    assert _plan(steps) == []


def test_plan_windows_found_when_solar_exceeds_threshold():
    # solar=2000W, base=20W, surplus=1980W, dc_w=1720W → coverage=1.0 > 0.5
    steps = _make_steps([2000.0] * 8)   # 2h of good solar
    windows = _plan(steps)
    assert len(windows) == 1


def test_plan_windows_window_time_bounds_correct():
    # 4 steps of high solar, starting at _T0
    steps = _make_steps([2000.0] * 4)
    windows = _plan(steps)
    assert len(windows) == 1
    assert windows[0].start == _T0
    # end = start of step after the last one
    assert windows[0].end == _T0 + timedelta(minutes=4 * STEP_MINUTES)


def test_plan_windows_short_window_filtered_out():
    # min_period_steps=4 (1h), but only 2 good steps (30 min)
    steps = _make_steps([2000.0, 2000.0, 0.0, 0.0])
    assert _plan(steps, min_period_steps=4) == []


def test_plan_windows_gap_merging():
    # 2 good steps, 1 bad step, 2 good steps — gap=1 ≤ merge_gap=2 → single window
    steps = _make_steps([2000.0, 2000.0, 0.0, 2000.0, 2000.0])
    windows = _plan(steps, merge_gap_steps=2, min_period_steps=1)
    assert len(windows) == 1
    assert windows[0].start == steps[0].time
    assert windows[0].end == steps[4].time + timedelta(minutes=STEP_MINUTES)


def test_plan_windows_gap_too_large_stays_separate():
    # gap=3 > merge_gap=2 → two separate windows (each ≥ min_period_steps=2)
    steps = _make_steps([2000.0, 2000.0, 0.0, 0.0, 0.0, 2000.0, 2000.0])
    windows = _plan(steps, merge_gap_steps=2, min_period_steps=2)
    assert len(windows) == 2


def test_plan_windows_max_per_day_respected():
    # All 96 steps are sunny → should yield only 1 window per day when max_per_day=1
    steps = _make_steps([2000.0] * 96)
    windows = _plan(steps, max_per_day=1)
    dates = {w.start.date() for w in windows}
    # Only one date (all steps are 2026-06-23), so at most 1 window
    assert len(windows) <= 1


def test_plan_windows_soc_buffer_excludes_steps():
    # projected_soc just above min_soc: soc=0.22, min_soc=0.20, buffer=0.05 → excluded
    steps = _make_steps([2000.0] * 4, soc=0.22)
    windows = _plan(steps, min_soc=0.20, min_soc_buffer=0.05)
    assert windows == []


def test_plan_windows_soc_above_buffer_allows_steps():
    # soc=0.30, min_soc=0.20, buffer=0.05 → soc - min_soc = 0.10 > buffer → allowed
    steps = _make_steps([2000.0] * 4, soc=0.30)
    windows = _plan(steps, min_soc=0.20, min_soc_buffer=0.05)
    assert len(windows) == 1


def test_plan_windows_solar_energy_accounting():
    # 4 steps at 2000W solar, base=20W, wallbox_dc=1720W, all surplus covers wallbox
    steps = _make_steps([2000.0] * 4, soc=0.70)
    windows = _plan(steps)
    w = windows[0]
    # solar_wh = min(1720, 1980) * 4 * 0.25h = 1720 * 1h = 1720 Wh
    assert w.solar_wh == pytest.approx(1720 * 4 * (STEP_MINUTES / 60.0), rel=0.01)
    # battery_wh should be ~0 since solar covers the full wallbox draw
    assert w.battery_wh == pytest.approx(0.0, abs=1.0)


def test_plan_windows_bias_ratio_scales_near_term():
    # With bias_ratio=2.0 on 500W solar, effective solar = 1000W
    # 1000W - 20W base = 980W surplus; 1720W dc_w → coverage = 980/1720 ≈ 0.57 > 0.5 → candidate
    steps = _make_steps([500.0] * 4, soc=0.70)
    windows_no_bias = _plan(steps, bias_ratio=1.0, bias_steps=8)
    windows_biased = _plan(steps, bias_ratio=2.0, bias_steps=8)
    assert windows_no_bias == []
    assert len(windows_biased) == 1


# ---------------------------------------------------------------------------
# ForecastWallboxAgent — integration-style tests
# ---------------------------------------------------------------------------

def test_fw_agent_name():
    assert ForecastWallboxAgent().name == "forecast_wallbox"


def test_fw_agent_not_fast_cycle():
    assert ForecastWallboxAgent.fast_cycle is False


def test_fw_agent_inactive_without_forecast():
    proj = _fw_projection(steps=_make_steps([2000.0] * 8), forecast=None)
    # Override forecast to None
    proj = SystemProjection(current=proj.current, forecast=None,
                            horizon_hours=2, steps=proj.steps)
    result = ForecastWallboxAgent().run(proj, _fw_cfg())
    assert result.actions == []
    assert "no solar forecast" in result.rationale


def test_fw_agent_wallbox_off_outside_window(monkeypatch):
    # All zero solar → no windows → wallbox should be OFF
    steps = _make_steps([0.0] * 96)
    proj = _fw_projection(steps, solar_now=0.0)
    result = ForecastWallboxAgent().run(proj, _fw_cfg())
    due = [a for a in result.actions if a.is_due(window_seconds=60.0)]
    assert len(due) == 1
    assert due[0].actuator == "wallbox_charge"
    assert due[0].value == 0


def test_fw_agent_wallbox_on_inside_window(monkeypatch):
    # High solar for 4h starting NOW — current time is inside the window
    # _T0 is the first step; monkeypatch datetime.now() to _T0 + 30min (inside window)
    from unittest.mock import patch

    steps = _make_steps([2000.0] * 96, soc=0.70)
    proj = _fw_projection(steps, solar_now=2000.0)
    proj.current.timestamp = _T0

    target_now = _T0 + timedelta(minutes=30)  # 30 min into the window

    with patch("control.agents.forecast_wallbox.datetime") as mock_dt:
        mock_dt.now.return_value = target_now
        result = ForecastWallboxAgent().run(proj, _fw_cfg())

    due = [a for a in result.actions if a.execute_at == target_now]
    assert len(due) == 1
    assert due[0].value == 1
    assert due[0].actuator == "wallbox_charge"


def test_fw_agent_metrics_always_present():
    steps = _make_steps([0.0] * 4)
    proj = _fw_projection(steps, solar_now=0.0)
    result = ForecastWallboxAgent().run(proj, _fw_cfg())
    for key in ("wallbox_power_w", "planned_windows", "total_solar_wh",
                "total_battery_wh", "solar_bias_ratio"):
        assert key in result.metrics


def test_fw_agent_future_transitions_in_schedule():
    # Window starts at _T0; run agent at _T0 - 1h so window is entirely in the future
    from unittest.mock import patch

    steps = _make_steps([2000.0] * 96, soc=0.70)
    proj = _fw_projection(steps, solar_now=2000.0)

    past_now = _T0 - timedelta(hours=1)

    with patch("control.agents.forecast_wallbox.datetime") as mock_dt:
        mock_dt.now.return_value = past_now
        result = ForecastWallboxAgent().run(proj, _fw_cfg())

    future_on = [a for a in result.actions
                 if a.actuator == "wallbox_charge" and a.value == 1 and a.execute_at > past_now]
    assert len(future_on) >= 1


def test_fw_agent_bias_ratio_reported_in_metrics():
    # forecast_now=1000W, actual=500W → bias=0.5
    steps = _make_steps([1000.0] * 4, soc=0.70)
    forecast = SolarForecast(
        fetched_at=_T0,
        entries=[HourlyEntry(time=_T0 + timedelta(hours=h), mppt150_w=1000.0, mppt100_w=0.0)
                 for h in range(10)],
    )
    proj = _fw_projection(steps, forecast=forecast, solar_now=500.0)
    result = ForecastWallboxAgent().run(proj, _fw_cfg())
    assert result.metrics["solar_bias_ratio"] == pytest.approx(0.5, rel=0.01)
