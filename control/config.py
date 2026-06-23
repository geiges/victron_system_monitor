import dataclasses
import yaml
from dataclasses import dataclass, field
from pathlib import Path

from config_default import batt_config_V1 as _batt


@dataclass
class BatteryConfig:
    capacity_ah: float = _batt["Q_tot"]
    r0: float = _batt["R0"]
    r1: float = _batt["R1"]
    c1: float = _batt["C1"]
    ncells: int = _batt["ncells"]
    charge_efficiency: float = _batt["charge_efficiency"]
    min_soc: float = _batt["low_battery_SOC"]
    min_voltage: float = _batt["min_safety_voltage"]
    max_voltage: float = _batt["max_safety_voltage"]
    min_temp: float = _batt["min_safety_temperature"]
    max_temp: float = _batt["max_safety_temperature"]

    @classmethod
    def from_dict(cls, d: dict) -> "BatteryConfig":
        valid = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class ForecastConfig:
    computepi_base_url: str = "http://192.168.1.93:5100"
    endpoint_id: str = "homesolar"
    mppt150_file: str = "forecast_solar_yield_5312439980_mppt150.csv"
    mppt100_file: str = "forecast_solar_yield_5312439980_mppt100.csv"
    cache_minutes: int = 60
    max_age_hours: int = 6

    @classmethod
    def from_dict(cls, d: dict) -> "ForecastConfig":
        valid = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class SystemSafetyConfig:
    enabled: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "SystemSafetyConfig":
        return cls(enabled=bool(d.get("enabled", True)))


@dataclass
class TimeBasedConfig:
    enabled: bool = False
    inverter_on_before_sunset_min: int = 30
    inverter_off_after_sunrise_min: int = 30

    @classmethod
    def from_dict(cls, d: dict) -> "TimeBasedConfig":
        valid = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class ForecastAwareConfig:
    enabled: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "ForecastAwareConfig":
        return cls(enabled=bool(d.get("enabled", False)))


@dataclass
class SocWallboxChargeConfig:
    enabled: bool = True
    soc_on_threshold: float = 0.99   # SOC considered "full"
    soc_on_minutes: int = 30         # minutes at full before turning on
    soc_off_threshold: float = 0.25  # SOC below which wallbox is turned off

    @classmethod
    def from_dict(cls, d: dict) -> "SocWallboxChargeConfig":
        valid = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class AgentsConfig:
    system_safety: SystemSafetyConfig = field(default_factory=SystemSafetyConfig)
    time_based: TimeBasedConfig = field(default_factory=TimeBasedConfig)
    forecast_aware: ForecastAwareConfig = field(default_factory=ForecastAwareConfig)
    soc_wallbox_charge: SocWallboxChargeConfig = field(default_factory=SocWallboxChargeConfig)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentsConfig":
        return cls(
            system_safety=SystemSafetyConfig.from_dict(d.get("system_safety", {})),
            time_based=TimeBasedConfig.from_dict(d.get("time_based", {})),
            forecast_aware=ForecastAwareConfig.from_dict(d.get("forecast_aware", {})),
            soc_wallbox_charge=SocWallboxChargeConfig.from_dict(d.get("soc_wallbox_charge", {})),
        )


@dataclass
class ActuatorsConfig:
    multiplus_mode: bool = True
    multiplus_mode_on: int = 3
    multiplus_mode_off: int = 4
    mppt100_load: bool = True
    mppt100_load_on: int = 1
    mppt100_load_off: int = 0
    wallbox_charge: bool = True
    wallbox_tasmota_url: str = "http://tasmota-158A57-2647"
    wallbox_tasmota_fallback_url: str = "http://192.168.1.185"

    @classmethod
    def from_dict(cls, d: dict) -> "ActuatorsConfig":
        valid = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass
class ControlConfig:
    safety_interval_seconds: int = 60
    control_interval_seconds: int = 300
    horizon_hours: int = 48
    estimated_load_w: float = 20.0
    battery: BatteryConfig = field(default_factory=BatteryConfig)
    forecast: ForecastConfig = field(default_factory=ForecastConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    actuators: ActuatorsConfig = field(default_factory=ActuatorsConfig)

    @classmethod
    def from_dict(cls, d: dict) -> "ControlConfig":
        return cls(
            safety_interval_seconds=int(d.get("safety_interval_seconds", 60)),
            control_interval_seconds=int(d.get("control_interval_seconds", 300)),
            horizon_hours=int(d.get("horizon_hours", 24)),
            estimated_load_w=float(d.get("estimated_load_w", 200.0)),
            battery=BatteryConfig.from_dict(d.get("battery", {})),
            forecast=ForecastConfig.from_dict(d.get("forecast", {})),
            agents=AgentsConfig.from_dict(d.get("agents", {})),
            actuators=ActuatorsConfig.from_dict(d.get("actuators", {})),
        )

    @classmethod
    def load(cls, path: Path) -> "ControlConfig":
        with open(path) as f:
            return cls.from_dict(yaml.safe_load(f) or {})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(dataclasses.asdict(self), f,
                      default_flow_style=False, allow_unicode=True, sort_keys=False)

    @classmethod
    def load_or_default(cls, path: Path) -> "ControlConfig":
        if path.exists():
            print(f"loading file {path}")
            return cls.load(path)
        else:
            print("loading defaults to config")
            cfg = cls()
            cfg.save(path)
            return cfg
