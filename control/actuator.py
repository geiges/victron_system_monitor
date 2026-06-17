"""Execute scheduled actions via dbus-send (D-Bus) or HTTP (Tasmota).

D-Bus service addresses (ttyUSB numbers) are looked up at runtime from
data/system_configuration.yaml, which the D-Bus logger writes on startup.
Tasmota URLs come directly from ActuatorsConfig.
"""
import subprocess
from pathlib import Path
from typing import Optional

import requests
import yaml

from control.schedule import ScheduledAction
from control.config import ActuatorsConfig


# D-Bus actuators: name → (component name in system_config, D-Bus path)
_DBUS_SPECS = {
    "multiplus_mode": ("multiplus", "/Mode"),
    "mppt100_load":   ("mppt100",   "/Load/State"),
}

# Tasmota actuators: name → (primary URL attr, fallback URL attr)
_TASMOTA_SPECS = {
    "wallbox_charge": ("wallbox_tasmota_url", "wallbox_tasmota_fallback_url"),
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


def _execute_dbus_action(
    action: ScheduledAction,
    config: ActuatorsConfig,
    system_config_path: Path,
) -> bool:
    component_name, dbus_path = _DBUS_SPECS[action.actuator]
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


def _execute_tasmota_action(action: ScheduledAction, config: ActuatorsConfig) -> bool:
    url_attr, fallback_attr = _TASMOTA_SPECS[action.actuator]
    primary = getattr(config, url_attr, "")
    fallback = getattr(config, fallback_attr, "")
    urls = [u for u in (primary, fallback) if u]

    if not urls:
        print(f"[actuator] no URL configured for {action.actuator!r}")
        return False

    cmd = f"Power {action.value}"
    for url in urls:
        try:
            resp = requests.get(
                f"{url.rstrip('/')}/cm",
                params={"cmnd": cmd},
                timeout=5,
            )
            resp.raise_for_status()
            print(f"[actuator] {action.actuator}={action.value} → {url} OK")
            return True
        except Exception as exc:
            print(f"[actuator] {action.actuator} failed at {url}: {exc}")
    return False


def execute_action(
    action: ScheduledAction,
    config: ActuatorsConfig,
    system_config_path: Path = Path("data/system_configuration.yaml"),
) -> bool:
    """Execute a ScheduledAction. Returns True on success."""
    if action.actuator in _TASMOTA_SPECS:
        return _execute_tasmota_action(action, config)
    if action.actuator in _DBUS_SPECS:
        return _execute_dbus_action(action, config, system_config_path)
    print(f"[actuator] unknown actuator: {action.actuator!r}")
    return False
