import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from battery import Battery

from control.forecast import SolarForecast
from control.state import CurrentState


@dataclass
class ProjectedHour:
    time: datetime
    solar_w: float
    estimated_load_w: float
    projected_soc: float


@dataclass
class SystemProjection:
    current: CurrentState
    forecast: Optional[SolarForecast]
    horizon_hours: int
    hours: list  # list[ProjectedHour]


def _make_battery(cfg) -> Battery:
    return Battery(
        total_capacity=cfg.battery.capacity_ah,
        R0=cfg.battery.r0,
        R1=cfg.battery.r1,
        C1=cfg.battery.c1,
        cells=cfg.battery.ncells,
        charge_efficiency=cfg.battery.charge_efficiency,
    )


def _step_soc(battery: Battery, solar_w: float, load_w: float) -> float:
    """Advance battery SOC by one hour given net power flows.

    Uses coulomb counting only (hourly resolution makes RC transient negligible).
    Sign convention: positive current = charging (matches Victron/simulation.py).
    """
    ocv = battery.OCV
    net_current = (solar_w - load_w) / ocv if ocv > 0 else 0.0
    delta_as = net_current * 3600.0 * battery.charge_efficiency
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

        hours = []
        for h in range(cfg.horizon_hours):
            t = current.timestamp + timedelta(hours=h + 1)
            solar_w = forecast.get_hour(t) if forecast is not None else 0.0
            load_w = cfg.estimated_load_w
            soc = _step_soc(battery, solar_w, load_w)
            hours.append(ProjectedHour(
                time=t,
                solar_w=solar_w,
                estimated_load_w=load_w,
                projected_soc=soc,
            ))

        return SystemProjection(
            current=current,
            forecast=forecast,
            horizon_hours=cfg.horizon_hours,
            hours=hours,
        )
    
    def create_log_entry(self, projection: SystemProjection, log) -> None:
        projected_socs = [h.projected_soc for h in projection.hours]
        
        key_metrics = {
        "min_soc": min(projected_socs) if projected_socs else None,
        "max_soc": max(projected_socs) if projected_socs else None,
        "min_soc_hour": projected_socs.index(min(projected_socs)) + 1
                        if projected_socs else None,
        "max_soc_hour": projected_socs.index(max(projected_socs)) + 1
                        if projected_socs else None
                        }
        
        log.append(f"[projection] done (with base load: {self._config.estimated_load_w} W) :" + 
                   f"min SOC={key_metrics['min_soc']:.1%} (in {key_metrics['min_soc_hour']}h), "+ 
                   f"maxSOC={key_metrics['max_soc']:.1%} (in {key_metrics['max_soc_hour']}h)")


def save_projection_csv(projection: SystemProjection, path: Path) -> None:
    """Write the projected hourly states to a CSV file (overwritten each cycle)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "solar_w", "estimated_load_w", "projected_soc"])
        for h in projection.hours:
            writer.writerow([
                h.time.strftime("%Y-%m-%d %H:%M"),
                round(h.solar_w, 1),
                round(h.estimated_load_w, 1),
                round(h.projected_soc, 4),
            ])
