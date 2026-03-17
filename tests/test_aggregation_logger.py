"""
Tests for AggregationLogger – daily energy aggregation from per-second CSV logs.
No D-Bus connection required.

Test dataset (tests/data/agg/)
-------------------------------
log_26-03-15.csv  – steady solar/load day, easy to hand-verify:
    2 intervals × 10 s, mppt100/DC_0_voltage=28.0 V, mppt100/DC_load_current=2.0 A
    DC_load_power  = 28.0 × 2.0 × 20 s = 1120 Ws = 1120/3 600 000 kWh
    AC_power_output= 100.0          × 20 s = 2000 Ws = 2000/3 600 000 kWh
    solar_total    = (50.02−50.00) + (200.02−200.00) = 0.04 kWh

log_26-03-16.csv  – night; zero AC, no solar yield change.
"""
import csv
import os

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config_default as config
from dbus_logger import AggregationLogger

# ---------------------------------------------------------------------------
# Paths and expected values
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "agg")
LOG_15 = "log_26-03-15.csv"
LOG_16 = "log_26-03-16.csv"

ENERGY_DC   = 1120 / 3_600_000   # kWh – DC load (mppt100)
ENERGY_AC   = 2000 / 3_600_000   # kWh – AC output (multiplus)
SOLAR_15    = round(0.04, config.round_digits)   # both chargers combined


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _make_logger(tmp_path, last_date="26-03-14"):
    """
    Return a logger whose output dir already contains daily.csv with one row,
    so __init__ skips _init_output_file and we control last_date_str.
    """
    out_dir = tmp_path / "aggregations"
    out_dir.mkdir()
    header = "date,DC_load_power,AC_power_output,solar_total\n"
    row    = f"{last_date},0.0001,0.0002,0.010\n"
    (out_dir / "daily.csv").write_text(header + row)
    return AggregationLogger(config, input_dir=DATA_DIR, output_dir=str(out_dir))


# ---------------------------------------------------------------------------
# _get_last_date_logged
# ---------------------------------------------------------------------------
def test_get_last_date_no_file(tmp_path):
    """Returns 'NaT' when the daily.csv does not exist."""
    logger = _make_logger(tmp_path)
    os.remove(logger.cfg["out_filepath"])
    assert logger._get_last_date_logged() == "NaT"


def test_get_last_date_reads_last_row(tmp_path):
    """Reads the date from the last line of an existing daily.csv."""
    logger = _make_logger(tmp_path, last_date="26-03-14")
    assert logger.last_date_str == "26-03-14"


def test_get_last_date_multirow(tmp_path):
    """Returns the date of the most recent row when multiple rows exist."""
    logger = _make_logger(tmp_path, last_date="26-03-14")
    with open(logger.cfg["out_filepath"], "a") as f:
        f.write("26-03-15,0.0003,0.0004,0.020\n")
    assert logger._get_last_date_logged() == "26-03-15"


# ---------------------------------------------------------------------------
# _compute_day_aggregates
# ---------------------------------------------------------------------------
def test_compute_day_aggregates_date(tmp_path):
    """The 'date' field is extracted correctly from the filename."""
    logger = _make_logger(tmp_path)
    result = logger._compute_day_aggregates(LOG_15)
    assert result["date"] == "26-03-15"


def test_compute_day_aggregates_dc_energy(tmp_path):
    """DC load energy is integrated correctly (V × I × Δt → kWh)."""
    logger = _make_logger(tmp_path)
    result = logger._compute_day_aggregates(LOG_15)
    assert result["DC_load_power"] == pytest.approx(ENERGY_DC, rel=1e-4)


def test_compute_day_aggregates_ac_energy(tmp_path):
    """AC output energy is integrated correctly (P × Δt → kWh)."""
    logger = _make_logger(tmp_path)
    result = logger._compute_day_aggregates(LOG_15)
    assert result["AC_power_output"] == pytest.approx(ENERGY_AC, rel=1e-4)


def test_compute_day_aggregates_solar_total(tmp_path):
    """solar_total is the sum of all chargers' yield differences (last − first)."""
    logger = _make_logger(tmp_path)
    result = logger._compute_day_aggregates(LOG_15)
    assert result["solar_total"] == SOLAR_15


def test_compute_day_aggregates_zero_solar_night(tmp_path):
    """Night file: zero AC output and no solar yield change."""
    logger = _make_logger(tmp_path)
    result = logger._compute_day_aggregates(LOG_16)
    assert result["solar_total"] == 0.0
    assert result["AC_power_output"] == pytest.approx(0.0, abs=1e-9)


def test_compute_day_aggregates_single_row(tmp_path, tmp_path_factory):
    """A file with a single data row produces zero energy (no interval)."""
    single_row_dir = tmp_path_factory.mktemp("single")
    csv_path = single_row_dir / "log_26-03-17.csv"
    csv_path.write_text(
        "time,mppt100/DC_0_voltage,mppt100/DC_load_current,"
        "multiplus/AC_power_output,mppt100/total_yield,mppt150/total_yield\n"
        "12:00:00,28.0,2.0,100.0,50.0,200.0\n"
    )
    logger = _make_logger(tmp_path, last_date="26-03-16")
    logger.cfg["input_dir"] = str(single_row_dir)
    result = logger._compute_day_aggregates("log_26-03-17.csv")
    assert result["DC_load_power"]   == pytest.approx(0.0, abs=1e-9)
    assert result["AC_power_output"] == pytest.approx(0.0, abs=1e-9)
    assert result["solar_total"]     == 0.0


# ---------------------------------------------------------------------------
# update_daily_aggregates
# ---------------------------------------------------------------------------
def test_update_same_day_no_write(tmp_path):
    """No rows are appended when called with the same date as last_date_str."""
    logger = _make_logger(tmp_path, last_date="26-03-15")
    logger.update_daily_aggregates("26-03-15")
    with open(logger.cfg["out_filepath"]) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1


def test_update_one_day_gap(tmp_path):
    """A 2-day jump aggregates the one missed day (26-03-15)."""
    logger = _make_logger(tmp_path, last_date="26-03-14")
    logger.update_daily_aggregates("26-03-16")
    with open(logger.cfg["out_filepath"]) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[1]["date"] == "26-03-15"


def test_update_multi_day_gap(tmp_path):
    """A 3-day jump aggregates both missed days (26-03-15 and 26-03-16)."""
    logger = _make_logger(tmp_path, last_date="26-03-14")
    logger.update_daily_aggregates("26-03-17")
    with open(logger.cfg["out_filepath"]) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert rows[1]["date"] == "26-03-15"
    assert rows[2]["date"] == "26-03-16"


def test_update_advances_last_date(tmp_path):
    """last_date_str is updated to the new date after aggregation."""
    logger = _make_logger(tmp_path, last_date="26-03-14")
    logger.update_daily_aggregates("26-03-16")
    assert logger.last_date_str == "26-03-16"


def test_update_current_day_not_aggregated(tmp_path):
    """The current (still-running) day is never written to daily.csv.

    With last_date='26-03-14' and date_str='26-03-17', the range logic
    range(1, time_delta.days) yields offsets [1, 2] → 26-03-15 and 26-03-16.
    26-03-17 (offset 3) is intentionally excluded because the day is incomplete.
    """
    logger = _make_logger(tmp_path, last_date="26-03-14")
    logger.update_daily_aggregates("26-03-17")
    with open(logger.cfg["out_filepath"]) as f:
        rows = list(csv.DictReader(f))
    dates = [r["date"] for r in rows]
    assert "26-03-17" not in dates
    assert len(rows) == 3  # original seed row + 26-03-15 + 26-03-16


def test_update_aggregated_values_written(tmp_path):
    """The appended row contains correct solar_total for 26-03-15."""
    logger = _make_logger(tmp_path, last_date="26-03-14")
    logger.update_daily_aggregates("26-03-16")
    with open(logger.cfg["out_filepath"]) as f:
        rows = list(csv.DictReader(f))
    assert float(rows[1]["solar_total"]) == pytest.approx(SOLAR_15, rel=1e-4)


# ---------------------------------------------------------------------------
# _init_output_file
# ---------------------------------------------------------------------------
def test_init_output_file_backfills_history(tmp_path):
    """_init_output_file creates daily.csv with one row per log file found."""
    logger = _make_logger(tmp_path)
    os.remove(logger.cfg["out_filepath"])
    logger._init_output_file()
    with open(logger.cfg["out_filepath"]) as f:
        rows = list(csv.DictReader(f))
    # DATA_DIR contains log_26-03-15.csv, log_26-03-16.csv, log_26-03-17.csv
    assert len(rows) == 3
    assert rows[0]["date"] == "26-03-15"
    assert rows[1]["date"] == "26-03-16"
    assert rows[2]["date"] == "26-03-17"
