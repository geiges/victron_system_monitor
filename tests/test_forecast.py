from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from control.config import ForecastConfig
from control.forecast import SolarForecastProvider, HourlyEntry, _parse_csv, _merge


MPPT150_CSV = """\
time,0
2026-06-17 06:00:00,
2026-06-17 07:00:00,50.0
2026-06-17 12:00:00,800.0
2026-06-17 20:00:00,10.0
2026-06-17 21:00:00,0.0
"""

MPPT100_CSV = """\
time,0
2026-06-17 07:00:00,30.0
2026-06-17 12:00:00,400.0
2026-06-17 20:00:00,5.0
"""


def _make_provider(base_url="http://fake:5100", max_age_hours=24):
    cfg = ForecastConfig(
        computepi_base_url=base_url,
        endpoint_id="homesolar",
        mppt150_file="mppt150.csv",
        mppt100_file="mppt100.csv",
        cache_minutes=60,
        max_age_hours=max_age_hours,
    )
    return SolarForecastProvider(cfg)


def _mock_get(url, **kwargs):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if "mppt150" in url:
        resp.text = MPPT150_CSV
    else:
        resp.text = MPPT100_CSV
    return resp


# --- _parse_csv ---

def test_parse_csv_skips_empty_values():
    data = _parse_csv(MPPT150_CSV)
    t_06 = datetime(2026, 6, 17, 6, 0, 0)
    t_07 = datetime(2026, 6, 17, 7, 0, 0)
    assert t_06 not in data          # empty value → skipped
    assert data[t_07] == pytest.approx(50.0)


def test_parse_csv_parses_all_non_empty():
    data = _parse_csv(MPPT150_CSV)
    assert len(data) == 4            # 07, 12, 20, 21 have values


# --- _merge ---

def test_merge_sums_arrays():
    m150 = _parse_csv(MPPT150_CSV)
    m100 = _parse_csv(MPPT100_CSV)
    entries = _merge(m150, m100)
    totals = {e.time: e.total_w for e in entries}

    t12 = datetime(2026, 6, 17, 12, 0, 0)
    assert totals[t12] == pytest.approx(1200.0)  # 800 + 400


def test_merge_union_of_times():
    m150 = _parse_csv(MPPT150_CSV)
    m100 = _parse_csv(MPPT100_CSV)
    entries = _merge(m150, m100)
    times = {e.time for e in entries}
    # 21:00 only in mppt150; all mppt100 times present
    assert datetime(2026, 6, 17, 21, 0, 0) in times
    assert datetime(2026, 6, 17, 7, 0, 0) in times


# --- SolarForecastProvider ---

def test_get_returns_forecast_on_success():
    provider = _make_provider()
    with patch("control.forecast.requests.get", side_effect=_mock_get):
        forecast = provider.get()

    assert forecast is not None
    assert len(forecast.entries) > 0


def test_get_hour_returns_correct_total():
    provider = _make_provider()
    with patch("control.forecast.requests.get", side_effect=_mock_get):
        forecast = provider.get()

    t = datetime(2026, 6, 17, 12, 30, 0)  # within the 12:00 hour
    assert forecast.get_hour(t) == pytest.approx(1200.0)


def test_get_hour_missing_returns_zero():
    provider = _make_provider()
    with patch("control.forecast.requests.get", side_effect=_mock_get):
        forecast = provider.get()

    t = datetime(2026, 6, 17, 3, 0, 0)  # no entry for 03:00
    assert forecast.get_hour(t) == pytest.approx(0.0)


def test_get_returns_none_on_http_error():
    provider = _make_provider()
    with patch("control.forecast.requests.get", side_effect=ConnectionError("unreachable")):
        forecast = provider.get()

    assert forecast is None


def test_cache_prevents_second_fetch():
    provider = _make_provider()
    with patch("control.forecast.requests.get", side_effect=_mock_get) as mock_get:
        provider.get()
        provider.get()

    assert mock_get.call_count == 2   # two files per fetch, called once total


def test_stale_cache_returned_on_fetch_failure():
    provider = _make_provider()
    with patch("control.forecast.requests.get", side_effect=_mock_get):
        first = provider.get()

    # Force cache age past cache_minutes but within max_age_hours
    provider._cache.fetched_at = datetime(2026, 6, 17, 0, 0, 0)

    with patch("control.forecast.requests.get", side_effect=ConnectionError("down")):
        result = provider.get()

    assert result is first  # stale cache returned
