import json
from datetime import datetime, timedelta

from control.config import ControlConfig
from control.forecast import SolarForecast, HourlyEntry
from control.projection import SystemProjection, make_battery
from control.state import CurrentState
from control.agents.wallbox_optimal_charge import (
    WallboxOptimalChargeAgent, _plan_day, _simulate_day, _mismatch_cost, _day_buckets,
)

_CFG = ControlConfig()
_BASE_HOUR = datetime(2026, 6, 17, 0, 0, 0)


def _state(soc=0.5, ts=_BASE_HOUR):
    return CurrentState(
        timestamp=ts, soc=soc, battery_voltage=25.4, battery_current=0.0,
        battery_temp=25.0, solar_power_w=0.0, ac_load_w=200.0,
        mppt_150_power_w=0.0, mppt_100_power_w=0.0,
    )


def _forecast(hourly_w, start=_BASE_HOUR):
    entries = [
        HourlyEntry(time=start + timedelta(hours=i), mppt150_w=w, mppt100_w=0.0)
        for i, w in enumerate(hourly_w)
    ]
    return SolarForecast(fetched_at=start, entries=entries)


def _projection(soc, forecast):
    return SystemProjection(current=_state(soc=soc), forecast=forecast, horizon_hours=24, steps=[])


# ---------------------------------------------------------------------------
# _day_buckets
# ---------------------------------------------------------------------------

def test_day_buckets_first_bucket_is_partial():
    start = datetime(2026, 6, 17, 14, 0, 0)
    buckets = _day_buckets(start, horizon_days=2)
    assert buckets[0][0] == start
    assert buckets[0][-1].date() == start.date()
    assert len(buckets[0]) == 10  # 14:00..23:00


def test_day_buckets_full_days_have_24_hours():
    start = datetime(2026, 6, 17, 0, 0, 0)
    buckets = _day_buckets(start, horizon_days=3)
    assert [len(b) for b in buckets] == [24, 24, 24]


# ---------------------------------------------------------------------------
# _mismatch_cost
# ---------------------------------------------------------------------------

def test_mismatch_cost_zero_when_wallbox_exactly_cancels_surplus():
    solar_w = [1200.0, 1200.0]
    cost = _mismatch_cost(solar_w, base_load_w=200.0, wallbox_w=1000.0, start=0, duration=2)
    assert cost == 0.0


def test_mismatch_cost_positive_when_mismatched():
    solar_w = [1200.0, 1200.0]
    cost = _mismatch_cost(solar_w, base_load_w=200.0, wallbox_w=1000.0, start=0, duration=1)
    assert cost > 0.0


# ---------------------------------------------------------------------------
# _plan_day
# ---------------------------------------------------------------------------

def test_plan_day_picks_window_matching_surplus():
    battery = make_battery(_CFG)
    solar_w = [0.0] * 6 + [2000.0] * 4 + [0.0] * 14  # surplus at hours 6-9
    choice, end_soc = _plan_day(
        battery, solar_w, base_load_w=200.0, wallbox_w=1600.0,
        min_storage_fraction=0.25, start_soc=0.5,
    )
    assert choice is not None
    start, duration = choice
    assert 6 <= start <= 9
    assert duration >= 1


def test_plan_day_full_soc_still_charges_during_surplus():
    """Battery starting at 100% SOC with a sunny window must still activate
    the wallbox to capture the otherwise-curtailed solar (the case that
    ruled out a pure SOC-delta cost function)."""
    battery = make_battery(_CFG)
    solar_w = [2000.0] * 24  # sun all day, battery already full
    choice, end_soc = _plan_day(
        battery, solar_w, base_load_w=200.0, wallbox_w=1600.0,
        min_storage_fraction=0.25, start_soc=1.0,
    )
    assert choice is not None
    start, duration = choice
    assert duration > 0


def test_plan_day_weak_solar_still_charges_if_day_reaches_full_soc():
    """Regression: a day whose peak solar never comes close to covering the
    wallbox must still schedule some charging if the (already high) starting
    SOC means the battery tops out and curtails anyway — a whole-day
    mismatch-cost comparison alone always favored "no charge" here, silently
    wasting the curtailed hours (see _min_charge_duration)."""
    battery = make_battery(_CFG)
    solar_w = [300.0] * 24  # peak 300W, nowhere near the ~1720W wallbox draw
    choice, end_soc = _plan_day(
        battery, solar_w, base_load_w=20.0, wallbox_w=1600.0,
        min_storage_fraction=0.25, start_soc=0.95,
    )
    assert choice is not None
    start, duration = choice
    assert duration >= 1


def test_plan_day_low_solar_picks_no_charge():
    battery = make_battery(_CFG)
    solar_w = [50.0] * 24  # well below base load, never worth activating
    choice, end_soc = _plan_day(
        battery, solar_w, base_load_w=200.0, wallbox_w=1600.0,
        min_storage_fraction=0.25, start_soc=0.5,
    )
    assert choice is None


def test_plan_day_rejects_floor_breaching_full_day_window():
    solar_w = [1000.0] * 12 + [0.0] * 12
    base_load_w = 200.0
    wallbox_w = 1600.0 / 0.93
    min_storage_fraction = 0.25
    start_soc = 0.30

    # Sanity check: running the wallbox the entire day from this starting SOC
    # does breach the floor (otherwise this test proves nothing).
    naive_battery = make_battery(_CFG)
    naive_min_soc, _ = _simulate_day(
        naive_battery, solar_w, base_load_w, wallbox_w, start=0, duration=24,
        start_soc=start_soc,
    )
    assert naive_min_soc < min_storage_fraction

    battery = make_battery(_CFG)
    choice, _ = _plan_day(
        battery, solar_w, base_load_w, wallbox_w, min_storage_fraction, start_soc,
    )
    verify_battery = make_battery(_CFG)
    if choice is None:
        min_soc, _ = _simulate_day(
            verify_battery, solar_w, base_load_w, wallbox_w, 0, 0, start_soc,
        )
    else:
        start, duration = choice
        assert duration < 24
        min_soc, _ = _simulate_day(
            verify_battery, solar_w, base_load_w, wallbox_w, start, duration, start_soc,
        )
    assert min_soc >= min_storage_fraction


# ---------------------------------------------------------------------------
# WallboxOptimalChargeAgent — integration
# ---------------------------------------------------------------------------

def test_agent_inactive_without_forecast(tmp_path):
    result = WallboxOptimalChargeAgent(tmp_path).run(_projection(0.5, None), _CFG)
    assert result.actions == []
    assert "no solar forecast" in result.rationale


def test_agent_dispatches_via_sequence_not_bare_actuator(tmp_path):
    """The agent must request the staged wallbox_on/wallbox_off sequences
    (inverter + DC load + wallbox, with verification) rather than writing the
    wallbox_charge actuator directly."""
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    hourly_w = [0.0] * 6 + [3000.0] * 6 + [0.0] * 12  # surplus 6h from now
    forecast = _forecast(hourly_w, start=now)
    result = WallboxOptimalChargeAgent(tmp_path).run(_projection(0.5, forecast), _CFG)
    assert result.metrics["planned_windows"] >= 1
    assert result.actions == []  # no bare actuator writes
    assert len(result.sequences) == 1
    intent = result.sequences[0]
    assert intent.sequence_name == "wallbox_off"  # "now" (start of forecast) is outside the window
    assert intent.agent == "wallbox_optimal_charge"


def test_agent_requests_wallbox_on_sequence_inside_window(tmp_path):
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    hourly_w = [3000.0] * 24  # surplus right now too
    forecast = _forecast(hourly_w, start=now)
    result = WallboxOptimalChargeAgent(tmp_path).run(_projection(0.5, forecast), _CFG)
    assert len(result.sequences) == 1
    assert result.sequences[0].sequence_name == "wallbox_on"


def test_agent_saves_schedule_file(tmp_path):
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    hourly_w = [0.0] * 6 + [3000.0] * 6 + [0.0] * 12
    forecast = _forecast(hourly_w, start=now)
    cfg = ControlConfig()
    WallboxOptimalChargeAgent(tmp_path).run(_projection(0.5, forecast), cfg)

    path = tmp_path / "wallbox_optimal_charge_schedule.json"
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload["wallbox_power_w"] == cfg.agents.wallbox_optimal_charge.wallbox_power_w
    assert len(payload["rows"]) == cfg.agents.wallbox_optimal_charge.horizon_days * 24
    row = payload["rows"][0]
    assert set(row) == {"time", "solar_w", "wallbox_on", "projected_soc"}
    assert any(r["wallbox_on"] for r in payload["rows"])
