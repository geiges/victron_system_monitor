"""Execute scheduled D-Bus actions via dbus-send.

Service addresses (ttyUSB numbers) are looked up at runtime from
data/system_configuration.yaml, which the D-Bus logger writes on startup.
"""
import subprocess
from pathlib import Path
from typing import Optional

import yaml

from control.schedule import ScheduledAction
from control.config import ActuatorsConfig


# Maps actuator name → (component short name in system_config, D-Bus path)
_ACTUATOR_SPECS = {
    "multiplus_mode": ("multiplus", "/Mode"),
    "mppt100_load":   ("mppt100",   "/Load/State"),
}


def _get_service(system_config_path: Path, component_name: str) -> Optional[str]:
    """Return the D-Bus service name for a component, or None if unavailable."""
    try:
        with open(system_config_path) as f:
            data = yaml.safe_load(f) or {}
        comp = data.get("components", {}).get(component_name, {})
        if not comp.get("available", False):
            return None
        return comp.get("service")
    except (OSError, yaml.YAMLError) as exc:
        print(f"[actuator] cannot read system config: {exc}")
        return None


def execute_action(
    action: ScheduledAction,
    config: ActuatorsConfig,
    system_config_path: Path = Path("data/system_configuration.yaml"),
) -> bool:
    """Execute a ScheduledAction via dbus-send. Returns True on success."""
    spec = _ACTUATOR_SPECS.get(action.actuator)
    if spec is None:
        print(f"[actuator] unknown actuator: {action.actuator!r}")
        return False

    component_name, dbus_path = spec
    service = _get_service(system_config_path, component_name)
    if service is None:
        print(f"[actuator] component {component_name!r} not available in system config")
        return False

    cmd = [
        "dbus-send", "--system", "--print-reply",
        f"--dest={service}",
        dbus_path,
        "com.victronenergy.BusItem.SetValue",
        f"variant:int32:{action.value}",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"[actuator] {action.actuator}={action.value} → {service}{dbus_path} OK")
            return True
        print(f"[actuator] {action.actuator}={action.value} FAILED: {result.stderr.strip()}")
        return False
    except Exception as exc:
        print(f"[actuator] {action.actuator}={action.value} ERROR: {exc}")
        return False
