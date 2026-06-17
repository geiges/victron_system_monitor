import csv
import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta

from control.state import read_current_state, StateUnavailableError, minutes_at_full_soc


# ---------------------------------------------------------------------------
# Helpers for minutes_at_full_soc tests
# ---------------------------------------------------------------------------

def _write_sim_csv(path, rows):
    """rows: list of (time: datetime, soc: float)"""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "SOC_counted", "SOC_Kf"])
        for t, soc in rows:
            writer.writerow([t.strftime("%H:%M:%S"), soc, soc])


def _sim_path(tmp_path, ref_date=None):
    d = ref_date or datetime.now().date()
    return tmp_path / f"sim_{d.strftime('%y-%m-%d')}.csv"


# ---------------------------------------------------------------------------
# minutes_at_full_soc tests
# ---------------------------------------------------------------------------

def test_minutes_at_full_soc_no_files_returns_none(tmp_path):
    assert minutes_at_full_soc(tmp_path) is None


def test_minutes_at_full_soc_empty_file_returns_none(tmp_path):
    _sim_path(tmp_path).write_text("time,SOC_counted,SOC_Kf\n")
    assert minutes_at_full_soc(tmp_path) is None


def test_minutes_at_full_soc_all_full_returns_minutes_since_start(tmp_path):
    now = datetime(2026, 6, 17, 14, 0, 0)
    path = tmp_path / "sim_26-06-17.csv"
    rows = [(now - timedelta(minutes=60 - i), 1.0) for i in range(60)]
    _write_sim_csv(path, rows)
    result = minutes_at_full_soc(tmp_path, _now=now)
    # First row was 60 minutes ago
    assert 59 <= result <= 61


def test_minutes_at_full_soc_recent_drop_returns_minutes_since_drop(tmp_path):
    now = datetime(2026, 6, 17, 14, 0, 0)
    path = tmp_path / "sim_26-06-17.csv"
    # SOC below full until 35 minutes ago, then full
    rows = []
    for i in range(60):
        t = now - timedelta(minutes=60 - i)
        soc = 0.50 if i < 25 else 1.0  # dropped below full 35 min ago
    rows = [(now - timedelta(minutes=60 - i), 0.50 if i < 25 else 1.0) for i in range(60)]
    _write_sim_csv(path, rows)
    result = minutes_at_full_soc(tmp_path, _now=now)
    assert 34 <= result <= 36


def test_minutes_at_full_soc_never_full_returns_zero(tmp_path):
    now = datetime(2026, 6, 17, 14, 0, 0)
    path = tmp_path / "sim_26-06-17.csv"
    rows = [(now - timedelta(minutes=30 - i), 0.80) for i in range(30)]
    _write_sim_csv(path, rows)
    result = minutes_at_full_soc(tmp_path, _now=now)
    # SOC never reached threshold — last row is below it, so result must be 0.0
    assert result == 0.0


def test_minutes_at_full_soc_stale_file_returns_none(tmp_path):
    """File not from today → None."""
    now = datetime(2026, 6, 17, 14, 0, 0)
    # Yesterday's file
    path = tmp_path / "sim_26-06-16.csv"
    rows = [(datetime(2026, 6, 16, 13, 0, 0) + timedelta(minutes=i), 1.0) for i in range(10)]
    _write_sim_csv(path, rows)
    assert minutes_at_full_soc(tmp_path, _now=now) is None


def test_minutes_at_full_soc_stale_last_entry_returns_none(tmp_path):
    """Latest row older than 1 minute → None."""
    now = datetime(2026, 6, 17, 14, 0, 0)
    path = tmp_path / "sim_26-06-17.csv"
    # Last row is 2 minutes old
    rows = [(now - timedelta(minutes=10 - i), 1.0) for i in range(9)]  # last = now - 1 min 10 s... wait
    # Make last row 2 minutes before now
    rows = [(now - timedelta(minutes=12 - i), 1.0) for i in range(10)]  # last = now - 2 min
    _write_sim_csv(path, rows)
    assert minutes_at_full_soc(tmp_path, _now=now) is None


def test_minutes_at_full_soc_fresh_entry_not_filtered(tmp_path):
    """Latest row within 1 minute → not filtered."""
    now = datetime(2026, 6, 17, 14, 0, 0)
    path = tmp_path / "sim_26-06-17.csv"
    # Rows oldest→newest: last row is now - 30s (fresh)
    rows = [(now - timedelta(seconds=75 - i * 5), 1.0) for i in range(10)]
    _write_sim_csv(path, rows)
    assert minutes_at_full_soc(tmp_path, _now=now) is not None


def test_minutes_at_full_soc_respects_custom_threshold(tmp_path):
    now = datetime(2026, 6, 17, 14, 0, 0)
    path = tmp_path / "sim_26-06-17.csv"
    # SOC at 0.95, which is full for threshold=0.90 but not for threshold=0.99
    rows = [(now - timedelta(minutes=30 - i), 0.95) for i in range(30)]
    _write_sim_csv(path, rows)
    assert minutes_at_full_soc(tmp_path, soc_full_threshold=0.90, _now=now) > 28
    assert minutes_at_full_soc(tmp_path, soc_full_threshold=0.99, _now=now) == 0.0


def _write_state(tmp_path, data):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "state.json").write_text(json.dumps(data))
    return tmp_path / "data"


def test_read_full_state(tmp_path):
    data_dir = _write_state(tmp_path, {
        "running_since": "26-06-17 10:00",
        "time": "14:30:00",
        "system/battery_voltage": 25.4,
        "system/battery_current": -3.2,
        "system/battery_temperature": 28.0,
        "system/power_yield": 620.0,
        "multiplus/AC_power_output": 380.0,
        "SOC_Kf": 0.72,
        "SOC_counted": 0.70,
    })
    state = read_current_state(data_dir)

    assert state.soc == pytest.approx(0.70)  # SOC_counted takes priority over SOC_Kf
    assert state.battery_voltage == pytest.approx(25.4)
    assert state.battery_current == pytest.approx(-3.2)
    assert state.battery_temp == pytest.approx(28.0)
    assert state.solar_power_w == pytest.approx(620.0)
    assert state.ac_load_w == pytest.approx(380.0)
    assert state.timestamp.hour == 14
    assert state.timestamp.minute == 30


def test_soc_fallback_to_kf(tmp_path):
    data_dir = _write_state(tmp_path, {
        "time": "08:00:00",
        "system/battery_voltage": 26.0,
        "system/battery_current": 5.0,
        "SOC_Kf": 0.55,
    })
    state = read_current_state(data_dir)
    assert state.soc == pytest.approx(0.55)


def test_soc_fallback_to_sim_csv(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "state.json").write_text(json.dumps({
        "time": "08:00:00",
        "system/battery_voltage": 26.0,
        "system/battery_current": 0.0,
    }))
    sim_csv = data_dir / "sim_26-06-17.csv"
    sim_csv.write_text(
        "time,SOC_Kf,SOC_counted\n"
        "08:00:00,0.63,0.61\n"
    )
    state = read_current_state(data_dir)
    assert state.soc == pytest.approx(0.63)


def test_solar_power_summed_from_mppt(tmp_path):
    data_dir = _write_state(tmp_path, {
        "time": "12:00:00",
        "system/battery_voltage": 25.0,
        "system/battery_current": 2.0,
        "mppt150/power_yield": 400.0,
        "mppt100/power_yield": 250.0,
        "SOC_Kf": 0.8,
    })
    state = read_current_state(data_dir)
    assert state.solar_power_w == pytest.approx(650.0)


def test_missing_state_file_raises(tmp_path):
    with pytest.raises(StateUnavailableError, match="state.json not found"):
        read_current_state(tmp_path / "nonexistent")


def test_missing_soc_raises(tmp_path):
    data_dir = _write_state(tmp_path, {
        "time": "08:00:00",
        "system/battery_voltage": 25.0,
        "system/battery_current": 0.0,
    })
    with pytest.raises(StateUnavailableError, match="SOC not available"):
        read_current_state(data_dir)


def test_missing_voltage_raises(tmp_path):
    data_dir = _write_state(tmp_path, {
        "time": "08:00:00",
        "SOC_Kf": 0.5,
        "system/battery_current": 0.0,
    })
    with pytest.raises(StateUnavailableError, match="Required fields missing"):
        read_current_state(data_dir)
