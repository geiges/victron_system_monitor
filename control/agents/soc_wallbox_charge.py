from datetime import datetime
from pathlib import Path

from control.agents.base import BaseAgent, AgentResult
from control.schedule import ScheduledAction
from control.state import minutes_at_full_soc


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

        metrics = {"soc": round(current.soc, 4)}

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
            return AgentResult(
                agent_name=self.name,
                actions=[],
                rationale=(
                    f"SOC {current.soc:.1%} above minimum {agent_cfg.soc_off_threshold:.0%}, "
                    f"below full threshold {agent_cfg.soc_on_threshold:.0%} — no action"
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

        return AgentResult(
            agent_name=self.name,
            actions=[],
            rationale=(
                f"SOC full for {minutes_full:.0f} min "
                f"(need {agent_cfg.soc_on_minutes} min) — waiting"
            ),
            metrics=metrics,
        )
