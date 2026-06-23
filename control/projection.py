import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from battery import Battery

from control.forecast import SolarForecast
from control.state import CurrentState

STEP_MINUTES = 15


@dataclass
class ProjectedStep:
    time: datetime
    solar_w: float
    estimated_load_w: float
    projected_soc: float


@dataclass
class SystemProjection:
    current: CurrentState
    forecast: Optional[SolarForecast]
    horizon_hours: int
    steps: list  # list[ProjectedStep]


def _make_battery(cfg) -> Battery:
    return Battery(
        total_capacity=cfg.battery.capacity_ah,
        R0=cfg.battery.r0,
        R1=cfg.battery.r1,
        C1=cfg.battery.c1,
        cells=cfg.battery.ncells,
        charge_efficiency=cfg.battery.charge_efficiency,
    )


def _step_soc(battery: Battery, solar_w: float, load_w: float, dt_seconds: float) -> float:
    """Advance battery SOC by dt_seconds given net power flows.

    Sign convention: positive current = charging (matches Victron/simulation.py).
    """
    ocv = battery.OCV
    net_current = (solar_w - load_w) / ocv if ocv > 0 else 0.0
    delta_as = net_current * dt_seconds * battery.charge_efficiency
    battery.actual_capacity = max(
        0.0, min(battery.total_capacity, battery.actual_capacity + delta_as)
    )
    return battery.state_of_charge


class BatteryProjector:
    def __init__(self, config):
        self._config = config
        print(config)

    def project(
        self,
        current: CurrentState,
        forecast: Optional[SolarForecast],
    ) -> SystemProjection:
        cfg = self._config
        battery = _make_battery(cfg)
        battery.set_state_of_charge(current.soc)

        dt_seconds = STEP_MINUTES * 60
        n_steps = cfg.horizon_hours * (60 // STEP_MINUTES)

        steps = []
        for i in range(n_steps):
            t = current.timestamp + timedelta(minutes=(i + 1) * STEP_MINUTES)
            solar_w = forecast.get_power(t) if forecast is not None else 0.0
            load_w = cfg.estimated_load_w
            soc = _step_soc(battery, solar_w, load_w, dt_seconds)
            steps.append(ProjectedStep(
                time=t,
                solar_w=solar_w,
                estimated_load_w=load_w,
                projected_soc=soc,
            ))

        return SystemProjection(
            current=current,
            forecast=forecast,
            horizon_hours=cfg.horizon_hours,
            steps=steps,
        )

    def create_log_entry(self, projection: SystemProjection, log) -> None:
        projected_socs = [s.projected_soc for s in projection.steps]
        if not projected_socs:
            log.append("[projection] done — no steps")
            return

        t0 = projection.current.timestamp
        min_soc = min(projected_socs)
        max_soc = max(projected_socs)
        min_step = projection.steps[projected_socs.index(min_soc)]
        max_step = projection.steps[projected_socs.index(max_soc)]
        min_h = (min_step.time - t0).total_seconds() / 3600
        max_h = (max_step.time - t0).total_seconds() / 3600

        log.append(
            f"[projection] done (base load {self._config.estimated_load_w} W): "
            f"min SOC={min_soc:.1%} (in {min_h:.2f}h), "
            f"max SOC={max_soc:.1%} (in {max_h:.2f}h)"
        )


def save_projection_csv(projection: SystemProjection, path: Path) -> None:
    """Write the projected steps to a CSV file (overwritten each cycle)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "solar_w", "estimated_load_w", "projected_soc"])
        for s in projection.steps:
            writer.writerow([
                s.time.strftime("%Y-%m-%d %H:%M"),
                round(s.solar_w, 1),
                round(s.estimated_load_w, 1),
                round(s.projected_soc, 4),
            ])
