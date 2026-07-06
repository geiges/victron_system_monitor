from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from control.agents.base import BaseAgent, AgentResult
from control.projection import make_battery, step_soc
from control.schedule import ScheduledAction


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
                   start: int, duration: int, start_soc: float) -> tuple[float, float]:
    """Clamped hourly SOC simulation for one day. Returns (min_soc, end_soc)."""
    battery.set_state_of_charge(start_soc)
    min_soc = start_soc
    for i, solar in enumerate(solar_w):
        active = start <= i < start + duration
        load_w = base_load_w + (wallbox_w if active else 0.0)
        soc = step_soc(battery, solar, load_w, dt_seconds=3600)
        min_soc = min(min_soc, soc)
    return min_soc, battery.state_of_charge


def _plan_day(battery, solar_w: list[float], base_load_w: float, wallbox_w: float,
              min_storage_fraction: float, start_soc: float,
              ) -> tuple[Optional[tuple[int, int]], float]:
    """Brute-force every (start, duration) block for one day (plus "no charge").

    Returns (winning (start, duration) or None, projected SOC at day's end).
    Candidates that would drop SOC below min_storage_fraction at any point
    during the day are rejected; among the rest, the lowest power-mismatch
    cost wins. Falls back to "no charge" if nothing stays above the floor.
    """
    n = len(solar_w)
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
        for bucket in buckets:
            solar_w = [projection.forecast.get_hour(t) for t in bucket]
            choice, soc = _plan_day(
                battery, solar_w, base_load_w, wallbox_dc_w,
                cfg.min_storage_fraction, soc,
            )
            if choice is not None:
                start, duration = choice
                windows.append(_DayWindow(
                    start=bucket[start],
                    end=bucket[start + duration - 1] + timedelta(hours=1),
                ))

        current_window = next((w for w in windows if w.start <= now < w.end), None)
        in_window = current_window is not None

        actions = []
        if config.actuators.wallbox_charge:
            if in_window:
                now_reason = (
                    f"inside optimal window "
                    f"{current_window.start.strftime('%H:%M')}–{current_window.end.strftime('%H:%M')}"
                )
            else:
                now_reason = "outside all optimal charge windows"
            actions.append(ScheduledAction(
                execute_at=now,
                actuator="wallbox_charge",
                value=1 if in_window else 0,
                reason=now_reason,
                agent=self.name,
            ))
            for w in windows:
                if w.start > now:
                    actions.append(ScheduledAction(
                        execute_at=w.start,
                        actuator="wallbox_charge",
                        value=1,
                        reason="optimal solar charge window",
                        agent=self.name,
                    ))
                if w.end > now:
                    actions.append(ScheduledAction(
                        execute_at=w.end,
                        actuator="wallbox_charge",
                        value=0,
                        reason="end of optimal solar charge window",
                        agent=self.name,
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

        return AgentResult(
            agent_name=self.name,
            actions=actions,
            rationale=rationale,
            metrics=metrics,
        )
