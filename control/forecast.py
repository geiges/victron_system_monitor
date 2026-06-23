import csv
import io
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests


_FORECAST_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_STALE_SENTINEL = object()  # distinct from None (which means "never fetched")


@dataclass
class HourlyEntry:
    time: datetime
    mppt150_w: float
    mppt100_w: float

    @property
    def total_w(self) -> float:
        return self.mppt150_w + self.mppt100_w


@dataclass
class SolarForecast:
    fetched_at: datetime
    entries: list  # list[HourlyEntry], sorted by time

    def get_hour(self, t: datetime) -> float:
        """Return total solar power W for the hour whose slot matches t."""
        for entry in self.entries:
            if (entry.time.year == t.year and entry.time.month == t.month
                    and entry.time.day == t.day and entry.time.hour == t.hour):
                return entry.total_w
        return 0.0

    def get_power(self, t: datetime) -> float:
        """Return interpolated total solar W at time t (linear between hourly entries)."""
        if not self.entries:
            return 0.0
        before = None
        after = None
        for entry in self.entries:
            if entry.time <= t:
                before = entry
            else:
                after = entry
                break
        if before is None:
            return after.total_w
        if after is None:
            return before.total_w
        span = (after.time - before.time).total_seconds()
        offset = (t - before.time).total_seconds()
        return before.total_w + (offset / span) * (after.total_w - before.total_w)


def _parse_csv(text: str) -> dict:
    """Parse a forecast CSV (columns: time, 0) into {datetime: float} dict."""
    result = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        raw = row.get("0", "").strip()
        if not raw:
            continue
        try:
            t = datetime.strptime(row["time"], _FORECAST_TIME_FMT)
            result[t] = float(raw)
        except (ValueError, KeyError):
            continue
    return result


def _merge(mppt150: dict, mppt100: dict) -> list:
    times = sorted(set(mppt150) | set(mppt100))
    return [
        HourlyEntry(
            time=t,
            mppt150_w=mppt150.get(t, 0.0),
            mppt100_w=mppt100.get(t, 0.0),
        )
        for t in times
    ]


class SolarForecastProvider:
    def __init__(self, config):
        self._cfg = config
        self._cache: Optional[SolarForecast] = None

    def get(self) -> Optional[SolarForecast]:
        if self._cache is not None:
            age_min = (datetime.now() - self._cache.fetched_at).total_seconds() / 60
            if age_min < self._cfg.cache_minutes:
                return self._cache

        try:
            fresh = self._fetch()
        except Exception as exc:
            print(f"[forecast] fetch failed: {exc}")
            return self._stale_or_none()

        if not self._is_recent_enough(fresh):
            print("[forecast] fetched data is too old, treating as unavailable")
            return None

        self._cache = fresh
        return self._cache

    def _fetch(self) -> SolarForecast:
        base = self._cfg.computepi_base_url.rstrip("/")
        ep = self._cfg.endpoint_id

        mppt150_text = self._get_file(f"{base}/files/{ep}/{self._cfg.mppt150_file}")
        mppt100_text = self._get_file(f"{base}/files/{ep}/{self._cfg.mppt100_file}")

        entries = _merge(_parse_csv(mppt150_text), _parse_csv(mppt100_text))
        return SolarForecast(fetched_at=datetime.now(), entries=entries)

    def _get_file(self, url: str) -> str:
        headers = {}
        api_key = os.environ.get("ECOWHEN_DATA_API_KEY", "")
        if api_key:
            headers["X-API-Key"] = api_key
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.text

    def _is_recent_enough(self, forecast: SolarForecast) -> bool:
        if not forecast.entries:
            return False
        latest = max(e.time for e in forecast.entries)
        cutoff = datetime.now() - timedelta(hours=self._cfg.max_age_hours)
        return latest >= cutoff

    def _stale_or_none(self) -> Optional[SolarForecast]:
        if self._cache is None:
            return None
        age_h = (datetime.now() - self._cache.fetched_at).total_seconds() / 3600
        if age_h > self._cfg.max_age_hours:
            return None
        return self._cache
