from datetime import datetime

from control.agents.base import BaseAgent, AgentResult
from control.schedule import ScheduledAction


class SystemSafetyAgent(BaseAgent):
    name = "system_safety"
    fast_cycle = True

    def is_enabled(self, config) -> bool:
        cfg = config.agents.system_safety
        return not (not cfg.enabled and cfg.confirmed_disable)

    def run(self, projection, config) -> AgentResult:
        current = projection.current
        bcfg = config.battery
        actcfg = config.actuators

        now = datetime.now()
        actions = []
        warnings = []

        soc_margin = current.soc - bcfg.min_soc
        min_voltage_margin = current.battery_voltage - bcfg.min_voltage
        max_voltage_margin = bcfg.max_voltage - current.battery_voltage
        voltage_margin = min(min_voltage_margin, max_voltage_margin)

        min_temp_margin = current.battery_temp - bcfg.min_temp
        max_temp_margin = bcfg.max_temp - current.battery_temp
        temp_margin = min(min_temp_margin, max_temp_margin)

        metrics = {
            "soc": round(current.soc, 4),
            "soc_margin": round(soc_margin, 4),
            "min_voltage_margin": round(min_voltage_margin, 2),
            "max_voltage_margin": round(max_voltage_margin, 2),
            "min_temp_margin": round(min_temp_margin, 1),
            "max_temp_margin": round(max_temp_margin, 1),
        }

        switch_off_AC = False

        if current.soc < bcfg.min_soc:
            warnings.append(
                f"SOC {current.soc:.1%} below limit {bcfg.min_soc:.1%}"
            )
            switch_off_AC = True

        if current.battery_voltage < bcfg.min_voltage:
            warnings.append(
                f"voltage {current.battery_voltage:.2f}V below limit {bcfg.min_voltage:.1f}V"
            )
            switch_off_AC = True

        if current.battery_voltage > bcfg.max_voltage:
            warnings.append(
                f"voltage {current.battery_voltage:.2f}V above limit {bcfg.max_voltage:.1f}V"
            )
            switch_off_AC = True

        # Over/under-temperature: stop AC via multiplus
        # (Solar MPPT chargers are not controllable in Phase 1)
        if current.battery_temp < bcfg.min_temp:
            warnings.append(
                f"temperature {current.battery_temp:.1f}°C below limit {bcfg.min_temp:.0f}°C"
            )
            switch_off_AC = True

        if current.battery_temp > bcfg.max_temp:
            warnings.append(
                f"temperature {current.battery_temp:.1f}°C above limit {bcfg.max_temp:.0f}°C"
            )
            switch_off_AC = True

        if switch_off_AC:
            reason = "; ".join(warnings)
            already_acted = any(a.actuator == "multiplus_mode" for a in actions)
            if actcfg.multiplus_mode and not already_acted:
                actions.append(ScheduledAction(
                    execute_at=now,
                    actuator="multiplus_mode",
                    value=actcfg.multiplus_mode_off,
                    reason=reason,
                    agent=self.name,
                ))

        if warnings:
            rationale = "SAFETY ACTION: " + "; ".join(warnings)
        else:
            rationale = (
                f"OK — SOC {current.soc:.1%} (margin {soc_margin:+.1%}), "
                f"voltage {current.battery_voltage:.2f}V (margin {voltage_margin:+.2f}V), "
                f"temp {current.battery_temp:.1f}°C (margin {temp_margin:.1f}°C)"
            )

        return AgentResult(
            agent_name=self.name,
            actions=actions,
            rationale=rationale,
            metrics=metrics,
        )
