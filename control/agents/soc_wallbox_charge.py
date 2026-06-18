from datetime import datetime
from pathlib import Path

from control.agents.base import BaseAgent, AgentResult
from control.schedule import ScheduledAction
from control.state import minutes_at_full_soc


def _hours_to_full(projection, threshold: float) -> int | None:
    """Return the first projected hour (1-based) where SOC reaches *threshold*, or None."""
    for i, h in enumerate(projection.hours):
        if h.projected_soc >= threshold:
            return i + 1
    return None


def _time_to_threshold_h(soc: float, threshold: float, current_a: float, capacity_ah: float) -> float | None:
    """Linear extrapolation of hours until SOC falls to *threshold*.

    Mirrors simulation.py's time_to_low_battery: only valid while discharging
    (current_a < -0.5 A) and when SOC is currently above *threshold*.
    """
    if current_a >= -0.5 or soc <= threshold:
        return None
    return (soc - threshold) * capacity_ah / (-current_a)


class SocWallboxChargeAgent(BaseAgent):
    """Switch wallbox on when battery has been full for long enough; off when low.

    Turn ON  — SOC has been >= soc_on_threshold for >= soc_on_minutes.
    Turn OFF — SOC drops below soc_off_threshold.
    """
    name = "soc_wallbox_charge"
    fast_cycle = True

    def __init__(self, data_dir: Path = Path("data")):
        self.data_dir = data_dir

    def run(self, projection, config) -> AgentResult:
        current = projection.current
        agent_cfg = config.agents.soc_wallbox_charge
        actcfg = config.actuators
        now = datetime.now()

        capacity_ah = config.battery.capacity_ah

        # Time to drop to the off-threshold at the current discharge rate (linear extrapolation)
        time_to_off_h = _time_to_threshold_h(
            current.soc, agent_cfg.soc_off_threshold,
            current.battery_current, capacity_ah,
        )

        metrics = {
            "soc": round(current.soc, 4),
            "time_to_off_threshold_h": round(time_to_off_h, 2) if time_to_off_h is not None else None,
        }

        # Turn off immediately if SOC is too low
        if current.soc < agent_cfg.soc_off_threshold:
            reason = (
                f"SOC {current.soc:.1%} below off-threshold {agent_cfg.soc_off_threshold:.1%}"
            )
            actions = []
            if actcfg.wallbox_charge:
                actions.append(ScheduledAction(
                    execute_at=now,
                    actuator="wallbox_charge",
                    value=0,
                    reason=reason,
                    agent=self.name,
                ))
            return AgentResult(
                agent_name=self.name,
                actions=actions,
                rationale=f"wallbox OFF — {reason}",
                metrics=metrics,
            )

        # SOC above minimum but not yet at full threshold — no action in either direction
        if current.soc < agent_cfg.soc_on_threshold:
            proj_h = _hours_to_full(projection, agent_cfg.soc_on_threshold)
            metrics["proj_hours_to_full"] = proj_h

            proj_part = f", projected full in ~{proj_h}h" if proj_h is not None else ", full not reached in forecast horizon"
            off_part = f", time to off-threshold: {time_to_off_h:.1f}h" if time_to_off_h is not None else ""

            return AgentResult(
                agent_name=self.name,
                actions=[],
                rationale=(
                    f"SOC {current.soc:.1%} — above minimum {agent_cfg.soc_off_threshold:.0%}, "
                    f"below full threshold {agent_cfg.soc_on_threshold:.0%}"
                    f"{proj_part}{off_part}"
                ),
                metrics=metrics,
            )

        # SOC at or above full threshold — check how long it has been there
        minutes_full = minutes_at_full_soc(self.data_dir, agent_cfg.soc_on_threshold)
        metrics["minutes_at_full"] = round(minutes_full, 1) if minutes_full is not None else None

        if minutes_full is None:
            return AgentResult(
                agent_name=self.name,
                actions=[],
                rationale="SOC history unavailable (no sim CSV) — no action",
                metrics=metrics,
            )

        if minutes_full >= agent_cfg.soc_on_minutes:
            reason = (
                f"SOC at full for {minutes_full:.0f} min "
                f"(threshold {agent_cfg.soc_on_minutes} min)"
            )
            actions = []
            if actcfg.wallbox_charge:
                actions.append(ScheduledAction(
                    execute_at=now,
                    actuator="wallbox_charge",
                    value=1,
                    reason=reason,
                    agent=self.name,
                ))
            return AgentResult(
                agent_name=self.name,
                actions=actions,
                rationale=f"wallbox ON — {reason}",
                metrics=metrics,
            )

        minutes_remaining = agent_cfg.soc_on_minutes - minutes_full
        return AgentResult(
            agent_name=self.name,
            actions=[],
            rationale=(
                f"SOC full for {minutes_full:.0f} min "
                f"(need {agent_cfg.soc_on_minutes} min, {minutes_remaining:.0f} min remaining) — waiting"
            ),
            metrics=metrics,
        )
