from datetime import datetime

from control.agents.base import BaseAgent, AgentResult
from control.schedule import ScheduledAction


def _switch_off_ac(actcfg):
    if not actcfg.multiplus_mode:
        return []
    return [("multiplus_mode", actcfg.multiplus_mode_off)]


def _switch_off_dc_load(actcfg):
    if not actcfg.mppt100_load:
        return []
    return [("mppt100_load", actcfg.mppt100_load_off)]

def _switch_on_dc_load(actcfg):
    if not actcfg.mppt100_load:
        return []
    return [("mppt100_load", actcfg.mppt100_load_on)]


def _switch_off_ac_mppt(actcfg):
    if not actcfg.ac_inverter_plug:
        return []
    return [("ac_inverter_plug", 0)]  # Tasmota smart plug: hard-cuts AC to the inverter


ACTIONS = {
    "switch_off_AC": _switch_off_ac,
    "switch_off_DC_load": _switch_off_dc_load,
    "switch_on_DC_load": _switch_on_dc_load,
    "switch_off_AC_mppt": _switch_off_ac_mppt,
}

# ponytail: one policy for every metric today — a low breach cuts what drains the
# battery (AC inverter mode + DC load), a high breach hard-cuts AC via the smart
# plug. Give a metric its own "action" dict when it needs to diverge.
_MIN_ACTIONS = ["switch_off_AC", "switch_off_DC_load"]
_MAX_ACTIONS = ["switch_off_AC_mppt"]

_FAN_ON_ACTION = ["switch_on_DC_load"]

class SystemSafetyAgent(BaseAgent):
    name = "system_safety"
    fast_cycle = True
    
    heat_memory= dict(cooling_mppt150_power=0, cooling_mppt100_power=0,
                      cooling_AC_load=0)

    def is_enabled(self, config) -> bool:
        True

    @staticmethod
    def _safety_metrics(bcfg):
        return {
            "soc": {
                "value": lambda s: s.soc*100,
                "min": bcfg.min_soc,
                "warn_min": .25,
                "warn_max" : None,
                "max": None,
                "label": "SOC",
                "fmt": ".0%",
                "action": {"min": _MIN_ACTIONS},
            },
            "voltage": {
                "value": lambda s: s.battery_voltage,
                "min": bcfg.min_voltage,
                "max": bcfg.max_voltage,
                "warn_min": 25,
                "warn_max" : 28.4,
                "label": "voltage",
                "fmt": ".2f",
                "unit": "V",
                "action": {"min": _MIN_ACTIONS, "max": _MAX_ACTIONS},
            },
            "temp": {
                "value": lambda s: s.battery_temp,
                "min": bcfg.min_temp,
                "max": bcfg.max_temp,
                "warn_min": 10,
                "warn_max" : 40,
                "label": "temperature",
                "fmt": ".1f",
                "unit": "°C",
                "action": {"min": _MIN_ACTIONS, "max": _MAX_ACTIONS},
                },
            "ac_load": {
                "value": lambda s: s.ac_load_w,
                "min": None,
                "max": bcfg.max_ac_load_w,
                "warn_min" : None,
                "warn_max" : 2200,
                "label": "AC load output",
                "fmt": ".1f",
                "unit": "W",
                "action": {"max": ["switch_off_AC"]},
                },
        
        }
    
    @staticmethod
    def _cooling_metrics(bcfg):
        return {
            "cooling_AC_load": {
                "value": lambda s: s.ac_load_w,
                "max": 1000,
                "label": "AC cooling load",
                "fmt": ".0f",
                "unit": "W",
                "action": {"max": _FAN_ON_ACTION},
                "n_req" : 6,
                },
            "cooling_mppt150_power": {
                "value": lambda s: s.mppt_150_power_w,
                "max": 600,
                "label": "MPPT150 cooling load",
                "fmt": ".0f",
                "unit": "W",
                "action": {"max": _FAN_ON_ACTION},
                "n_req" : 30,
                },
            "cooling_mppt100_power": {
                "value": lambda s: s.mppt_100_power_w,
                "max": 300,
                "label": "MPPT100 cooling load",
                "fmt": ".0f",
                "unit": "W",
                "action": {"max": _FAN_ON_ACTION},
                "n_req" : 30,
                },
            }
    

    def run(self, state, config) -> AgentResult:
        current = state
        actcfg = config.actuators
        now = datetime.now()

        warnings = []
        ok_parts = []
        metrics = dict()
        action_names = []
        #print(self._safety_metrics(config.battery))
        
        #safety control
        for key, spec in self._safety_metrics(config.battery).items():
            value = spec["value"](current)
            fmt, unit = spec["fmt"], spec.get("unit", "")
            margins = []
            
            metrics[f"{key}_value"] = value
            if spec["warn_min"] is not None:
                metrics[f"{key}_warn_min"] =  spec["warn_min"]
                
            if spec["warn_max"] is not None:
                metrics[f"{key}_warn_max"] =  spec["warn_max"]
            
            if spec["min"] is not None:
                margin = value - spec["min"]
                margins.append(margin)
                metrics[f"min_{key}_margin"] = round(margin, 4)
                if margin < 0:
                    warnings.append(
                        f"{spec['label']} {value:{fmt}}{unit} below limit {spec['min']:{fmt}}{unit}"
                    )
                    action_names += spec["action"].get("min", [])

            if spec["max"] is not None:
                margin = spec["max"] - value
                margins.append(margin)
                metrics[f"max_{key}_margin"] = round(margin, 4)
                if margin < 0:
                    warnings.append(
                        f"{spec['label']} {value:{fmt}}{unit} above limit {spec['max']:{fmt}}{unit}"
                    )
                    action_names += spec["action"].get("max", [])
            ok_parts.append(
                f"{spec['label']} {value:{fmt}}{unit} (margin {min(margins):+{fmt}}{unit})"
            )
            
        # cooling control
        for key, spec in self._cooling_metrics(config.battery).items():
            value = spec["value"](current)
            fmt, unit = spec["fmt"], spec.get("unit", "")
            
            if spec["max"] is not None:
                 margin = spec["max"] - value
                 margins.append(margin)
                 metrics[f"{key}_margin"] = round(margin, 4)
                 if margin < 0:
                     
                     self.heat_memory[key] = min( self.heat_memory[key] + 1, spec["n_req"]) 
                 else:
                     self.heat_memory[key] = max( self.heat_memory[key] - 1, 0)
                 
                     
                 if self.heat_memory[key] == spec["n_req"]:
                    warnings.append(
                        f"{spec['label']} heat limit reached"
                    )
                    action_names += spec["action"].get("max", [])
                 elif self.heat_memory[key] > 0:
                    warnings.append(
                          f"{spec['label']} at cooling level {self.heat_memory}/{spec['n_req']}"  
                    )
                    print(f"{spec['label']} at cooling level {self.heat_memory}/{spec['n_req']}" )
                
            
            
           

        actions = []
        seen_actuators = set()
        reason = "; ".join(warnings)
        for name in action_names:
            for actuator, act_value in ACTIONS[name](actcfg):
                if actuator in seen_actuators:
                    continue
                seen_actuators.add(actuator)
                actions.append(ScheduledAction(
                    execute_at=now,
                    actuator=actuator,
                    value=act_value,
                    reason=reason,
                    agent=self.name,
                ))

        if warnings:
            rationale = "SAFETY ACTION: " + reason
        else:
            rationale = "OK — " + ", ".join(ok_parts)

        return AgentResult(
            agent_name=self.name,
            actions=actions,
            rationale=rationale,
            metrics=metrics,
        )
