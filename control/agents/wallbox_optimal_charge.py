from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from control.agents.base import BaseAgent, AgentResult
from control.projection import make_battery, step_soc
from control.sequence import SequenceIntent

SCHEDULE_FILENAME = "wallbox_optimal_charge_schedule.json"


@dataclass
class _DayWindow:
    start: datetime
    end: datetime  # exclusive


def _day_buckets(start_hour: datetime, horizon_days: int) -> list[list[datetime]]:
    """Hourly timestamps from start_hour grouped by calendar date.

    The first bucket covers only the remaining hours of today; later buckets
    are full 24h days (the last bucket may also be partial, at the horizon
    boundary).
    """
    hours = [start_hour + timedelta(hours=i) for i in range(horizon_days * 24)]
    buckets: list[list[datetime]] = []
    for t in hours:
        if buckets and buckets[-1][-1].date() == t.date():
            buckets[-1].append(t)
        else:
            buckets.append([t])
    return buckets


def _mismatch_cost(solar_w: list[float], base_load_w: float, wallbox_w: float,
                    start: int, duration: int) -> float:
    """Raw power mismatch: how far consumption (load+wallbox) is from solar
    production, summed over the day. Deliberately ignores battery SOC so it
    rewards routing solar straight to the wallbox rather than round-tripping
    through the battery, and still rewards capturing solar that would
    otherwise be curtailed."""
    total = 0.0
    for i, solar in enumerate(solar_w):
        active = start <= i < start + duration
        load_w = base_load_w + (wallbox_w if active else 0.0)
        total += abs(solar - load_w)
    return total


def _simulate_day(battery, solar_w: list[float], base_load_w: float, wallbox_w: float,
                   start: int, duration: int, start_soc: float,
                   trace: Optional[list] = None) -> tuple[float, float]:
    """Clamped hourly SOC simulation for one day. Returns (min_soc, end_soc).

    If *trace* is given, the SOC after each hour is appended to it (used to
    record the winning candidate for the saved schedule; left None during the
    candidate search to avoid the extra bookkeeping)."""
    battery.set_state_of_charge(start_soc)
    min_soc = start_soc
    for i, solar in enumerate(solar_w):
        active = start <= i < start + duration
        load_w = base_load_w + (wallbox_w if active else 0.0)
        soc = step_soc(battery, solar, load_w, dt_seconds=3600)
        min_soc = min(min_soc, soc)
        if trace is not None:
            trace.append(soc)
    return min_soc, battery.state_of_charge


MIN_CHARGE_FRACTION = 0.5  # on a day that reaches 100% SOC, at least this
# fraction of the full-power hours needed to absorb the otherwise-curtailed
# solar must be scheduled — "no charge" is not a candidate on such a day.


def _wasted_wh(battery, solar_w: list[float], base_load_w: float, start_soc: float) -> float:
    """Solar (Wh) that curtails to waste if the wallbox never runs: the
    surplus during hours where the no-wallbox simulation is already pinned
    at 100% SOC."""
    trace: list[float] = []
    _simulate_day(battery, solar_w, base_load_w, 0.0, 0, 0, start_soc, trace=trace)
    return sum(
        max(0.0, solar - base_load_w)
        for solar, soc in zip(solar_w, trace)
        if soc >= 0.999
    )


def _plan_day(battery, solar_w: list[float], base_load_w: float, wallbox_w: float,
              min_storage_fraction: float, start_soc: float,
              ) -> tuple[Optional[tuple[int, int]], float]:
    """Brute-force every (start, duration) block for one day.

    Returns (winning (start, duration) or None, projected SOC at day's end).
    Candidates that would drop SOC below min_storage_fraction at any point
    during the day are rejected; among the rest, the lowest power-mismatch
    cost wins. Falls back to "no charge" if nothing stays above the floor.

    "No charge" is only itself a candidate on days that never reach 100% SOC
    — a whole-day mismatch-cost comparison otherwise always favors accepting
    curtailment over the (larger, but harmless given ample floor headroom)
    mismatch of running the wallbox on weak-solar days, which would silently
    waste hours of curtailed solar. See _wasted_wh.
    """
    n = len(solar_w)
    wasted_wh = _wasted_wh(battery, solar_w, base_load_w, start_soc)
    if wasted_wh > 0:
        hours_to_absorb = wasted_wh / wallbox_w
        min_duration = min(n, max(1, round(MIN_CHARGE_FRACTION * hours_to_absorb)))
        candidates = [
            (start, duration)
            for start in range(n)
            for duration in range(min_duration, n - start + 1)
        ]
    else:
        candidates = [(0, 0)] + [
            (start, duration)
            for start in range(n)
            for duration in range(1, n - start + 1)
        ]

    best_choice: Optional[tuple[int, int]] = None
    best_cost: Optional[float] = None
    best_end_soc = start_soc

    for start, duration in candidates:
        min_soc, end_soc = _simulate_day(
            battery, solar_w, base_load_w, wallbox_w, start, duration, start_soc,
        )
        if min_soc < min_storage_fraction:
            continue
        cost = _mismatch_cost(solar_w, base_load_w, wallbox_w, start, duration)
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_choice = (start, duration) if duration > 0 else None
            best_end_soc = end_soc

    if best_cost is None:
        # Nothing keeps storage above the floor (e.g. already very low) — don't charge.
        _, end_soc = _simulate_day(battery, solar_w, base_load_w, wallbox_w, 0, 0, start_soc)
        return None, end_soc

    return best_choice, best_end_soc


class WallboxOptimalChargeAgent(BaseAgent):
    """Day-by-day brute-force search for the wallbox block that best matches
    solar production, minimizing battery cycling while still capturing solar
    that would otherwise be curtailed. Alternative to ForecastWallboxAgent's
    coverage-threshold heuristic — mutually exclusive with it and with
    SocWallboxChargeAgent via the wallbox agent group."""

    name = "wallbox_optimal_charge"
    fast_cycle = False  # runs only on planning cycles (~5 min)

    def __init__(self, data_dir: Path = Path("data")):
        self.data_dir = data_dir

    def run(self, projection, config) -> AgentResult:
        if projection.forecast is None:
            return AgentResult(
                agent_name=self.name, actions=[],
                rationale="inactive — no solar forecast available",
                metrics={},
            )

        cfg = config.agents.wallbox_optimal_charge
        now = datetime.now()
        wallbox_dc_w = cfg.wallbox_power_w / cfg.inverter_efficiency
        base_load_w = config.estimated_load_w

        start_hour = now.replace(minute=0, second=0, microsecond=0)
        buckets = _day_buckets(start_hour, cfg.horizon_days)

        battery = make_battery(config)
        soc = projection.current.soc

        windows: list[_DayWindow] = []
        schedule_rows: list[dict] = []
        for bucket in buckets:
            solar_w = [projection.forecast.get_hour(t) for t in bucket]
            day_start_soc = soc
            choice, soc = _plan_day(
                battery, solar_w, base_load_w, wallbox_dc_w,
                cfg.min_storage_fraction, day_start_soc,
            )
            start, duration = choice if choice is not None else (0, 0)
            if choice is not None:
                windows.append(_DayWindow(
                    start=bucket[start],
                    end=bucket[start + duration - 1] + timedelta(hours=1),
                ))

            trace: list[float] = []
            _simulate_day(battery, solar_w, base_load_w, wallbox_dc_w,
                          start, duration, day_start_soc, trace=trace)
            for i, t in enumerate(bucket):
                schedule_rows.append({
                    "time": t.isoformat(),
                    "solar_w": round(solar_w[i], 1),
                    "wallbox_on": start <= i < start + duration,
                    "projected_soc": round(trace[i], 4),
                })

        current_window = next((w for w in windows if w.start <= now < w.end), None)
        in_window = current_window is not None

        # Dispatch through the staged wallbox_on/wallbox_off sequences (inverter +
        # DC load + wallbox, with verification/retries) rather than a bare
        # wallbox_charge actuator write — same pattern as SocWallboxChargeAgent's
        # wallbox_on, extended to wallbox_off too since our transitions aren't
        # safety-critical/urgent like that agent's low-SOC cutoff. Re-emitted every
        # planning cycle; SequenceRunner's per-sequence cooldown (control/sequence_runner.py)
        # makes repeatedly requesting the already-current state a no-op.
        #
        # execute_at is deliberately `now`, not `w.start`/`w.end`: this agent only
        # runs on planning cycles (~5 min, not clock-aligned), while is_due() only
        # accepts execute_at within +-30s of the real time. A fixed hour-boundary
        # timestamp would almost always already be stale by the time a cycle first
        # notices the crossing, so the intent would silently never fire.
        sequences = []
        if config.actuators.wallbox_charge:
            if in_window:
                now_reason = (
                    f"inside optimal window "
                    f"{current_window.start.strftime('%H:%M')}–{current_window.end.strftime('%H:%M')}"
                )
                sequences.append(SequenceIntent(
                    sequence_name="wallbox_on", execute_at=now,
                    agent=self.name, reason=now_reason,
                ))
            else:
                now_reason = "outside all optimal charge windows"
                sequences.append(SequenceIntent(
                    sequence_name="wallbox_off", execute_at=now,
                    agent=self.name, reason=now_reason,
                ))

        metrics = {
            "wallbox_power_w": cfg.wallbox_power_w,
            "planned_windows": len(windows),
            "projected_end_soc": round(soc, 3),
        }

        if windows:
            window_strs = [
                f"{w.start.strftime('%m-%d %H:%M')}–{w.end.strftime('%H:%M')}"
                for w in windows
            ]
            state_str = "ON" if in_window else "OFF"
            rationale = f"{state_str} — {len(windows)} window(s): {', '.join(window_strs)}"
        else:
            rationale = "no charge windows — no feasible solar surplus found"

        self._save_schedule(now, cfg, schedule_rows)

        return AgentResult(
            agent_name=self.name,
            actions=[],
            sequences=sequences,
            rationale=rationale,
            metrics=metrics,
        )

    def _save_schedule(self, now: datetime, cfg, rows: list[dict]) -> None:
        """Persist the planned solar/wallbox/SOC trace for offline inspection
        (e.g. agent_testenv.py-style plotting), overwritten each cycle."""
        path = self.data_dir / SCHEDULE_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": now.isoformat(),
            "wallbox_power_w": cfg.wallbox_power_w,
            "min_storage_fraction": cfg.min_storage_fraction,
            "rows": rows,
        }
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
