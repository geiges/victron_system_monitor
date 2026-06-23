from datetime import datetime, timedelta

import pytest

from control.config import ControlConfig
from control.forecast import SolarForecast, HourlyEntry
from control.projection import (
    BatteryProjector, STEP_MINUTES, _step_soc, _ceil_to_quarter,
)
from control.state import CurrentState
from battery import Battery


_BASE_TIME = datetime(2026, 6, 17, 20, 0, 0)  # already on a 15-min boundary
_STEP_S = STEP_MINUTES * 60                    # 900 s

_DEFAULT_CFG = ControlConfig()


def _state(soc=0.5, ts=_BASE_TIME):
    return CurrentState(
        timestamp=ts,
        soc=soc,
        battery_voltage=25.4,
        battery_current=0.0,
        battery_temp=25.0,
        solar_power_w=0.0,
        ac_load_w=200.0,
    )


def _forecast_constant(power_w, hours=24):
    entries = [
        HourlyEntry(
            time=_BASE_TIME + timedelta(hours=h + 1),
            mppt150_w=power_w,
            mppt100_w=0.0,
        )
        for h in range(hours)
    ]
    return SolarForecast(fetched_at=_BASE_TIME, entries=entries)


# ---------------------------------------------------------------------------
# _ceil_to_quarter — grid-snapping helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("08:30:00", "08:30"),
    ("08:30:01", "08:30"),   # seconds ignored; already on boundary
    ("08:37:22", "08:45"),
    ("08:44:59", "08:45"),
    ("08:45:00", "08:45"),
    ("08:59:59", "09:00"),
    ("00:00:00", "00:00"),
    ("23:46:00", "00:00"),   # wraps to next day midnight
])
def test_ceil_to_quarter(raw, expected):
    h, m, s = map(int, raw.split(":"))
    t = datetime(2026, 6, 17, h, m, s)
    result = _ceil_to_quarter(t)
    assert result.strftime("%H:%M") == expected


def test_ceil_to_quarter_returns_datetime_without_seconds():
    t = datetime(2026, 6, 17, 8, 37, 22)
    result = _ceil_to_quarter(t)
    assert result.second == 0
    assert result.microsecond == 0


# ---------------------------------------------------------------------------
# _step_soc unit tests
# ---------------------------------------------------------------------------

def test_step_soc_increases_when_solar_exceeds_load():
    battery = Battery(total_capacity=210, R0=0.01, R1=0.04, C1=2000, cells=8)
    battery.set_state_of_charge(0.5)
    new_soc = _step_soc(battery, solar_w=1000.0, load_w=200.0, dt_seconds=_STEP_S)
    assert new_soc > 0.5


def test_step_soc_decreases_when_only_load():
    battery = Battery(total_capacity=210, R0=0.01, R1=0.04, C1=2000, cells=8)
    battery.set_state_of_charge(0.5)
    new_soc = _step_soc(battery, solar_w=0.0, load_w=200.0, dt_seconds=_STEP_S)
    assert new_soc < 0.5


def test_step_soc_clamps_at_zero():
    battery = Battery(total_capacity=210, R0=0.01, R1=0.04, C1=2000, cells=8)
    battery.set_state_of_charge(0.0)
    new_soc = _step_soc(battery, solar_w=0.0, load_w=5000.0, dt_seconds=_STEP_S)
    assert new_soc == pytest.approx(0.0)


def test_step_soc_clamps_at_one():
    battery = Battery(total_capacity=210, R0=0.01, R1=0.04, C1=2000, cells=8)
    battery.set_state_of_charge(1.0)
    new_soc = _step_soc(battery, solar_w=100_000.0, load_w=0.0, dt_seconds=_STEP_S)
    assert new_soc == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# BatteryProjector — step count and timing
# ---------------------------------------------------------------------------

def test_projection_step_count_matches_horizon():
    projector = BatteryProjector(_DEFAULT_CFG)
    result = projector.project(_state(), forecast=None)
    expected = _DEFAULT_CFG.horizon_hours * (60 // STEP_MINUTES)
    assert len(result.steps) == expected


def test_projection_step_interval_is_15_minutes():
    projector = BatteryProjector(_DEFAULT_CFG)
    result = projector.project(_state(), forecast=None)
    for i in range(1, min(8, len(result.steps))):
        delta = (result.steps[i].time - result.steps[i - 1].time).total_seconds()
        assert delta == pytest.approx(900.0)


def test_projection_first_step_on_quarter_boundary_when_aligned():
    projector = BatteryProjector(_DEFAULT_CFG)
    result = projector.project(_state(ts=_BASE_TIME), forecast=None)  # 20:00 is aligned
    assert result.steps[0].time.minute % 15 == 0
    assert result.steps[0].time.second == 0


def test_projection_first_step_snapped_when_timestamp_mid_interval():
    ts = datetime(2026, 6, 17, 8, 37, 22)
    projector = BatteryProjector(_DEFAULT_CFG)
    result = projector.project(_state(ts=ts), forecast=None)
    first = result.steps[0].time
    assert first.minute % 15 == 0
    assert first.second == 0
    assert first == datetime(2026, 6, 17, 8, 45, 0)


def test_projection_all_steps_on_quarter_boundaries():
    ts = datetime(2026, 6, 17, 9, 23, 0)
    projector = BatteryProjector(_DEFAULT_CFG)
    result = projector.project(_state(ts=ts), forecast=None)
    for step in result.steps:
        assert step.time.minute % 15 == 0
        assert step.time.second == 0


# ---------------------------------------------------------------------------
# BatteryProjector — SOC physics
# ---------------------------------------------------------------------------

def test_projection_soc_decreases_without_solar():
    projector = BatteryProjector(_DEFAULT_CFG)
    result = projector.project(_state(soc=0.8), forecast=None)
    assert result.steps[-1].projected_soc < 0.8


def test_projection_soc_increases_with_high_solar():
    cfg = ControlConfig()
    cfg.estimated_load_w = 200.0
    projector = BatteryProjector(cfg)
    forecast = _forecast_constant(power_w=2000.0)
    result = projector.project(_state(soc=0.3), forecast=forecast)
    assert result.steps[-1].projected_soc > 0.3


def test_projection_soc_bounded_zero_to_one():
    cfg = ControlConfig()
    cfg.estimated_load_w = 5000.0
    projector = BatteryProjector(cfg)
    result = projector.project(_state(soc=0.1), forecast=None)
    for step in result.steps:
        assert 0.0 <= step.projected_soc <= 1.0


def test_projection_without_forecast_uses_zero_solar():
    projector = BatteryProjector(_DEFAULT_CFG)
    result = projector.project(_state(soc=0.5), forecast=None)
    for step in result.steps:
        assert step.solar_w == pytest.approx(0.0)


def test_projection_stores_forecast_reference():
    projector = BatteryProjector(_DEFAULT_CFG)
    forecast = _forecast_constant(power_w=500.0)
    result = projector.project(_state(), forecast=forecast)
    assert result.forecast is forecast


def test_projection_discharge_rate_roughly_correct():
    """With 200W load and no solar, 210Ah at ~26V (~5kWh) should be near empty after 27h."""
    cfg = ControlConfig()
    cfg.estimated_load_w = 200.0
    cfg.horizon_hours = 27
    projector = BatteryProjector(cfg)
    result = projector.project(_state(soc=1.0), forecast=None)
    assert result.steps[-1].projected_soc < 0.15
