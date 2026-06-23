from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from control.agents.base import BaseAgent, AgentResult
from control.projection import STEP_MINUTES
from control.schedule import ScheduledAction


@dataclass
class _ChargeWindow:
    start: datetime
    end: datetime       # exclusive — wallbox turns OFF at this exact time
    solar_wh: float     # wallbox energy drawn from solar surplus
    battery_wh: float   # additional battery energy due to wallbox (inverter losses included)


def _plan_windows(
    steps,
    base_load_w: float,
    wallbox_w: float,
    efficiency: float,
    max_per_day: int,
    min_period_steps: int,
    merge_gap_steps: int,
    min_solar_fraction: float,
    min_soc: float,
    min_soc_buffer: float,
    bias_ratio: float,
    bias_steps: int,
) -> list[_ChargeWindow]:
    """Find contiguous wallbox ON windows where solar adequately covers demand.

    Steps where projected SOC is within min_soc_buffer of min_soc are excluded
    so the wallbox never deepens an already-marginal battery state.
    """
    if not steps:
        return []

    dt_h = STEP_MINUTES / 60.0
    wallbox_dc_w = wallbox_w / efficiency  # DC-side equivalent (accounts for inverter losses)

    def eff_solar(i: int) -> float:
        raw = steps[i].solar_w
        return raw * bias_ratio if i < bias_steps else raw

    def coverage(i: int) -> float:
        """Fraction of wallbox_dc_w covered by solar surplus at step i."""
        if steps[i].projected_soc - min_soc < min_soc_buffer:
            return 0.0
        surplus = eff_solar(i) - base_load_w
        if wallbox_dc_w <= 0:
            return 0.0
        return min(1.0, max(0.0, surplus / wallbox_dc_w))

    # 1. Find raw contiguous candidate groups
    n = len(steps)
    raw: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if coverage(i) >= min_solar_fraction:
            j = i + 1
            while j < n and coverage(j) >= min_solar_fraction:
                j += 1
            raw.append((i, j))
            i = j
        else:
            i += 1

    if not raw:
        return []

    # 2. Merge windows whose gap is within merge_gap_steps
    merged: list[tuple[int, int]] = [raw[0]]
    for s, e in raw[1:]:
        prev_s, prev_e = merged[-1]
        if s - prev_e <= merge_gap_steps:
            merged[-1] = (prev_s, e)
        else:
            merged.append((s, e))

    # 3. Drop windows shorter than the minimum block duration
    valid = [(s, e) for s, e in merged if e - s >= min_period_steps]
    if not valid:
        return []

    # 4. Per-calendar-day: score by total solar yield, keep the best max_per_day
    by_day: dict = defaultdict(list)
    for s, e in valid:
        by_day[steps[s].time.date()].append((s, e))

    result: list[_ChargeWindow] = []
    for d in sorted(by_day):
        day_windows = by_day[d]

        def solar_yield(se, _eff=eff_solar, _base=base_load_w, _dt=dt_h):
            s, e = se
            return sum(max(0.0, _eff(i) - _base) * _dt for i in range(s, e))

        day_windows.sort(key=solar_yield, reverse=True)
        selected = sorted(day_windows[:max_per_day], key=lambda x: x[0])

        for s, e in selected:
            start_t = steps[s].time
            end_t = steps[e - 1].time + timedelta(minutes=STEP_MINUTES)
            solar_wh = sum(
                min(wallbox_dc_w, max(0.0, eff_solar(i) - base_load_w)) * dt_h
                for i in range(s, e)
            )
            battery_wh = max(0.0, (e - s) * wallbox_dc_w * dt_h - solar_wh)
            result.append(_ChargeWindow(
                start=start_t, end=end_t,
                solar_wh=round(solar_wh, 1),
                battery_wh=round(battery_wh, 1),
            ))

    return result


class ForecastWallboxAgent(BaseAgent):
    name = "forecast_wallbox"
    fast_cycle = False  # runs only on planning cycles (~5 min)

    def run(self, projection, config) -> AgentResult:
        if projection.forecast is None:
            return AgentResult(
                agent_name=self.name, actions=[],
                rationale="inactive — no solar forecast available",
                metrics={},
            )

        cfg = config.agents.forecast_wallbox
        now = datetime.now()
        steps = projection.steps

        if not steps:
            return AgentResult(
                agent_name=self.name, actions=[],
                rationale="inactive — projection has no steps",
                metrics={},
            )

        # Real-time bias: scale near-term forecast steps by actual/forecast ratio.
        # Applied only when the forecast is non-trivial to avoid divide-by-zero noise.
        forecast_now_w = projection.forecast.get_power(now)
        actual_now_w = projection.current.solar_power_w
        if forecast_now_w > 50.0:
            bias_ratio = min(3.0, max(0.1, actual_now_w / forecast_now_w))
        else:
            bias_ratio = 1.0
        bias_steps = 120 // STEP_MINUTES  # apply bias over the next 2 hours

        min_period_steps = max(1, cfg.min_period_minutes // STEP_MINUTES)
        merge_gap_steps = max(1, cfg.merge_gap_minutes // STEP_MINUTES)

        windows = _plan_windows(
            steps=steps,
            base_load_w=config.estimated_load_w,
            wallbox_w=cfg.wallbox_power_w,
            efficiency=cfg.inverter_efficiency,
            max_per_day=cfg.max_periods_per_day,
            min_period_steps=min_period_steps,
            merge_gap_steps=merge_gap_steps,
            min_solar_fraction=cfg.min_solar_fraction,
            min_soc=config.battery.min_soc,
            min_soc_buffer=0.05,
            bias_ratio=bias_ratio,
            bias_steps=bias_steps,
        )

        current_window = next((w for w in windows if w.start <= now < w.end), None)
        in_window = current_window is not None

        actions = []
        if config.actuators.wallbox_charge:
            # Emit current desired state every planning cycle (idempotent, acts as keepalive)
            if in_window:
                now_reason = (
                    f"inside solar window "
                    f"{current_window.start.strftime('%H:%M')}–{current_window.end.strftime('%H:%M')}"
                )
            else:
                now_reason = "outside all solar charge windows"
            actions.append(ScheduledAction(
                execute_at=now,
                actuator="wallbox_charge",
                value=1 if in_window else 0,
                reason=now_reason,
                agent=self.name,
            ))
            # Future ON/OFF transitions stored in schedule for display and just-in-time firing
            for w in windows:
                if w.start > now:
                    actions.append(ScheduledAction(
                        execute_at=w.start,
                        actuator="wallbox_charge",
                        value=1,
                        reason=(
                            f"solar window: {w.solar_wh:.0f}Wh solar, "
                            f"{w.battery_wh:.0f}Wh battery"
                        ),
                        agent=self.name,
                    ))
                if w.end > now:
                    actions.append(ScheduledAction(
                        execute_at=w.end,
                        actuator="wallbox_charge",
                        value=0,
                        reason="end of solar charge window",
                        agent=self.name,
                    ))

        total_solar_wh = sum(w.solar_wh for w in windows)
        total_battery_wh = sum(w.battery_wh for w in windows)
        metrics = {
            "wallbox_power_w": cfg.wallbox_power_w,
            "planned_windows": len(windows),
            "total_solar_wh": round(total_solar_wh),
            "total_battery_wh": round(total_battery_wh),
            "solar_bias_ratio": round(bias_ratio, 2),
        }

        if windows:
            window_strs = [
                f"{w.start.strftime('%m-%d %H:%M')}–{w.end.strftime('%H:%M')}"
                for w in windows
            ]
            state_str = "ON" if in_window else "OFF"
            rationale = (
                f"{state_str} — {len(windows)} window(s): {', '.join(window_strs)}; "
                f"solar {total_solar_wh:.0f}Wh, battery {total_battery_wh:.0f}Wh; "
                f"bias {bias_ratio:.2f}x"
            )
        else:
            rationale = (
                f"no charge windows — solar below threshold "
                f"(min_solar_fraction={cfg.min_solar_fraction:.0%}, bias={bias_ratio:.2f}x)"
            )

        return AgentResult(
            agent_name=self.name,
            actions=actions,
            rationale=rationale,
            metrics=metrics,
        )
