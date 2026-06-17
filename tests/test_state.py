import json
import pytest
from pathlib import Path
from datetime import datetime

from control.state import read_current_state, StateUnavailableError


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
