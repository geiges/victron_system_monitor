from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from control.config import ControlConfig
from control.forecast import SolarForecast, HourlyEntry
from control.projection import BatteryProjector, _step_soc
from control.state import CurrentState
from battery import Battery


_BASE_TIME = datetime(2026, 6, 17, 20, 0, 0)

_DEFAULT_CFG = ControlConfig()  # 210 Ah, horizon=24h, load=200W


def _state(soc=0.5):
    return CurrentState(
        timestamp=_BASE_TIME,
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


# --- _step_soc unit tests ---

def test_step_soc_increases_when_solar_exceeds_load():
    battery = Battery(total_capacity=210, R0=0.01, R1=0.04, C1=2000, cells=8)
    battery.set_state_of_charge(0.5)
    initial_soc = battery.state_of_charge
    new_soc = _step_soc(battery, solar_w=1000.0, load_w=200.0)
    assert new_soc > initial_soc


def test_step_soc_decreases_when_only_load():
    battery = Battery(total_capacity=210, R0=0.01, R1=0.04, C1=2000, cells=8)
    battery.set_state_of_charge(0.5)
    initial_soc = battery.state_of_charge
    new_soc = _step_soc(battery, solar_w=0.0, load_w=200.0)
    assert new_soc < initial_soc


def test_step_soc_clamps_at_zero():
    battery = Battery(total_capacity=210, R0=0.01, R1=0.04, C1=2000, cells=8)
    battery.set_state_of_charge(0.0)
    new_soc = _step_soc(battery, solar_w=0.0, load_w=5000.0)
    assert new_soc == pytest.approx(0.0)


def test_step_soc_clamps_at_one():
    battery = Battery(total_capacity=210, R0=0.01, R1=0.04, C1=2000, cells=8)
    battery.set_state_of_charge(1.0)
    new_soc = _step_soc(battery, solar_w=100_000.0, load_w=0.0)
    assert new_soc == pytest.approx(1.0)


# --- BatteryProjector integration ---

def test_projection_length_matches_horizon():
    projector = BatteryProjector(_DEFAULT_CFG)
    result = projector.project(_state(), forecast=None)
    assert len(result.hours) == _DEFAULT_CFG.horizon_hours


def test_projection_timestamps_are_sequential():
    projector = BatteryProjector(_DEFAULT_CFG)
    result = projector.project(_state(), forecast=None)
    for i, hour in enumerate(result.hours):
        expected = _BASE_TIME.replace(minute=0, second=0) if False else None
        # each step is 1 hour ahead of the previous
        if i > 0:
            delta = (hour.time - result.hours[i - 1].time).total_seconds()
            assert delta == pytest.approx(3600.0)


def test_projection_soc_decreases_without_solar():
    projector = BatteryProjector(_DEFAULT_CFG)
    result = projector.project(_state(soc=0.8), forecast=None)
    assert result.hours[-1].projected_soc < 0.8


def test_projection_soc_increases_with_high_solar():
    cfg = ControlConfig()
    cfg.estimated_load_w = 200.0
    projector = BatteryProjector(cfg)
    forecast = _forecast_constant(power_w=2000.0)
    result = projector.project(_state(soc=0.3), forecast=forecast)
    assert result.hours[-1].projected_soc > 0.3


def test_projection_soc_bounded_zero_to_one():
    cfg = ControlConfig()
    cfg.estimated_load_w = 5000.0   # drain faster than possible
    projector = BatteryProjector(cfg)
    result = projector.project(_state(soc=0.1), forecast=None)
    for hour in result.hours:
        assert 0.0 <= hour.projected_soc <= 1.0


def test_projection_without_forecast_uses_zero_solar():
    projector = BatteryProjector(_DEFAULT_CFG)
    result = projector.project(_state(soc=0.5), forecast=None)
    for hour in result.hours:
        assert hour.solar_w == pytest.approx(0.0)


def test_projection_stores_forecast_reference():
    projector = BatteryProjector(_DEFAULT_CFG)
    forecast = _forecast_constant(power_w=500.0)
    result = projector.project(_state(), forecast=forecast)
    assert result.forecast is forecast


def test_projection_discharge_rate_roughly_correct():
    """With 200W load and no solar, 210Ah at ~26V should last ~27h."""
    cfg = ControlConfig()
    cfg.estimated_load_w = 200.0
    cfg.horizon_hours = 27
    projector = BatteryProjector(cfg)
    result = projector.project(_state(soc=1.0), forecast=None)
    # After 27 hours draining 200W from 210Ah (≈5kWh) battery: should be near 0
    assert result.hours[-1].projected_soc < 0.15
