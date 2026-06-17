from datetime import datetime

from control.agents.base import BaseAgent, AgentResult
from control.schedule import ScheduledAction


class SystemSafetyAgent(BaseAgent):
    name = "system_safety"
    fast_cycle = True

    def run(self, projection, config) -> AgentResult:
        current = projection.current
        bcfg = config.battery
        actcfg = config.actuators

        now = datetime.now()
        actions = []
        warnings = []

        soc_margin = current.soc - bcfg.min_soc
        voltage_margin = current.battery_voltage - bcfg.min_voltage
        temp_margin = bcfg.max_temp - current.battery_temp

        metrics = {
            "soc": round(current.soc, 4),
            "soc_margin": round(soc_margin, 4),
            "voltage_margin": round(voltage_margin, 3),
            "temp_margin": round(temp_margin, 1),
        }

        # Under-voltage or low SOC: stop discharging immediately
        if current.soc < bcfg.min_soc:
            warnings.append(
                f"SOC {current.soc:.1%} below limit {bcfg.min_soc:.1%}"
            )
        if current.battery_voltage < bcfg.min_voltage:
            warnings.append(
                f"voltage {current.battery_voltage:.2f}V below limit {bcfg.min_voltage:.1f}V"
            )

        if warnings:
            reason = "; ".join(warnings)
            if actcfg.multiplus_mode:
                actions.append(ScheduledAction(
                    execute_at=now,
                    actuator="multiplus_mode",
                    value=actcfg.multiplus_mode_off,
                    reason=reason,
                    agent=self.name,
                ))

        # Over-temperature: stop charging via multiplus
        # (Solar MPPT chargers are not controllable in Phase 1)
        if current.battery_temp > bcfg.max_temp:
            temp_warn = (
                f"temperature {current.battery_temp:.1f}°C above limit {bcfg.max_temp:.0f}°C"
            )
            warnings.append(temp_warn)
            already_acted = any(a.actuator == "multiplus_mode" for a in actions)
            if actcfg.multiplus_mode and not already_acted:
                actions.append(ScheduledAction(
                    execute_at=now,
                    actuator="multiplus_mode",
                    value=actcfg.multiplus_mode_off,
                    reason=temp_warn,
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
