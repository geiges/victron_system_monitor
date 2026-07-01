from datetime import datetime
from pathlib import Path

import requests

from control.sequence import Sequence, SequenceStep
from control.schedule import ScheduledAction


def _now_action(actuator: str, value: int) -> ScheduledAction:
    return ScheduledAction(
        execute_at=datetime.now(),
        actuator=actuator,
        value=value,
        reason="sequence step",
        agent="wallbox_off",
    )


class WallboxOnSequence(Sequence):
    name = "wallbox_off"

    def build_steps(self, config, system_config_path: Path) -> list[SequenceStep]:
        from control.actuator import dbus_read_value, _get_service

        actcfg = config.actuators
        multiplus_svc = _get_service(system_config_path, "multiplus")
        mppt100_svc = _get_service(system_config_path, "mppt100")
        multiplus_mode_off = actcfg.multiplus_mode_on
        load_off = actcfg.mppt100_load_off
        wallbox_urls = [u for u in (actcfg.wallbox_tasmota_url, actcfg.wallbox_tasmota_fallback_url) if u]

        def verify_wallbox_off() -> bool:
            for url in wallbox_urls:
                try:
                    resp = requests.get(f"{url.rstrip('/')}/cm", params={"cmnd": "Power"}, timeout=5)
                    resp.raise_for_status()
                    return resp.json().get("POWER") == "OFF"
                except Exception:
                    continue
            return False

        return [
            SequenceStep(
                name="wallbox_off",
                action_fn=lambda: _now_action("wallbox_charge", 0),
                verify=verify_wallbox_off,
                max_retries=3,
            ),
            SequenceStep(
                name="dc_load_off",
                action_fn=lambda: _now_action("mppt100_load", load_off),
                verify=lambda: (
                    (i := dbus_read_value(mppt100_svc, "/Load/I")) is not None and i < 0.1
                ) if mppt100_svc else False,
                max_retries=5,
            ),
            SequenceStep(
                name="inverter_on",
                action_fn=lambda: _now_action("multiplus_mode", multiplus_mode_off),
                verify=lambda: dbus_read_value(multiplus_svc, "/Mode") == multiplus_mode_off if multiplus_svc else False,
                max_retries=3,
            ),
            
            
        ]
