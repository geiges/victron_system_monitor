#!/usr/bin/env python3
"""Battery control unit entry point.

Usage:
    uv run control_runner.py            # run continuous control loop
    uv run control_runner.py --dry-run  # print state/forecast/projection and exit
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from control.config import ControlConfig
from control.state import read_current_state, StateUnavailableError
from control.forecast import SolarForecastProvider
from control.projection import BatteryProjector
from control.schedule import Schedule
from control.decision_log import DecisionLog, build_log_entry
from control.actuator import execute_action

DATA_DIR = Path("data")
CONFIG_PATH = DATA_DIR / "control_config.yaml"
SCHEDULE_PATH = DATA_DIR / "control_schedule.json"
LOG_PATH = DATA_DIR / "control_log.jsonl"


def _load_agents():
    """Import and instantiate all agent classes."""
    from control.agents.system_safety import SystemSafetyAgent
    from control.agents.time_based import TimeBasedAgent
    from control.agents.forecast_aware import ForecastAwareAgent
    from control.agents.soc_wallbox_charge import SocWallboxChargeAgent
    return [
        SystemSafetyAgent(),
        SocWallboxChargeAgent(DATA_DIR),
        TimeBasedAgent(),
        ForecastAwareAgent(),
    ]


def _arbitrate(results: list) -> Schedule:
    """Merge agent results into a single schedule.

    Safety agent actions always take priority: if a safety action targets the
    same actuator as a planning agent, the safety action wins.
    """
    safety_actuators = set()
    safety_actions = []
    other_actions = []

    for result in results:
        if result.agent_name == "system_safety":
            safety_actions.extend(result.actions)
            safety_actuators.update(a.actuator for a in result.actions)
        else:
            other_actions.extend(result.actions)

    # Drop planning actions that conflict with safety decisions
    filtered = [a for a in other_actions if a.actuator not in safety_actuators]
    all_actions = safety_actions + sorted(filtered, key=lambda a: a.execute_at)
    return Schedule(created_at=datetime.now(), actions=all_actions)


def _sleep_to_next_interval(t_start: datetime, interval_seconds: int) -> None:
    elapsed = (datetime.now() - t_start).total_seconds()
    remaining = max(0.0, interval_seconds - elapsed)
    if remaining > 0:
        time.sleep(remaining)


def run_loop(config: ControlConfig) -> None:
    agents = _load_agents()
    forecast_provider = SolarForecastProvider(config.forecast)
    projector = BatteryProjector(config)
    log = DecisionLog(LOG_PATH)

    print(f"[runner] starting — safety={config.safety_interval_seconds}s, "
          f"planning={config.control_interval_seconds}s, "
          f"horizon={config.horizon_hours}h")

    last_planning_t = datetime.min  # force planning agents to run on first cycle

    while True:
        t_start = datetime.now()

        # Reload config each cycle so REST API edits take effect
        config = ControlConfig.load_or_default(CONFIG_PATH)
        projector = BatteryProjector(config)

        try:
            state = read_current_state(DATA_DIR)
        except StateUnavailableError as exc:
            print(f"[runner] state unavailable: {exc} — skipping cycle")
            _sleep_to_next_interval(t_start, config.safety_interval_seconds)
            continue

        forecast = forecast_provider.get()
        projection = projector.project(state, forecast)

        run_planning = (
            (t_start - last_planning_t).total_seconds()
            >= config.control_interval_seconds
        )

        results = []
        for agent in agents:
            if not agent.fast_cycle and not run_planning:
                continue
            if not agent.is_enabled(config):
                continue
            try:
                result = agent.run(projection, config)
                results.append(result)
                print(f"[{result.agent_name}] {result.rationale}")
            except Exception as exc:
                print(f"[runner] agent {agent.name} raised: {exc}")

        if run_planning:
            last_planning_t = t_start

        schedule = _arbitrate(results)
        schedule.save(SCHEDULE_PATH)

        for action in schedule.due_now():
            execute_action(action, config.actuators)

        entry = build_log_entry(state, forecast, projection, results, schedule)
        log.append(entry)

        print(f"[runner] cycle done — SOC={state.soc:.1%}, "
              f"projected_min={entry['projection']['min_soc']:.1%}, "
              f"actions={len(schedule.actions)}")

        _sleep_to_next_interval(t_start, config.safety_interval_seconds)


# ---------------------------------------------------------------------------
# Dry-run output
# ---------------------------------------------------------------------------

def _print_dry_run(config: ControlConfig) -> None:
    print("=== Control Runner — dry run ===\n")

    print("[config]")
    print(f"  horizon_hours          : {config.horizon_hours}")
    print(f"  control_interval_s     : {config.control_interval_seconds}")
    print(f"  estimated_load_w       : {config.estimated_load_w}")
    print(f"  battery capacity_ah    : {config.battery.capacity_ah}")
    print(f"  forecast url           : {config.forecast.computepi_base_url}")
    print()

    print("[current state]")
    try:
        state = read_current_state(DATA_DIR)
        print(f"  timestamp       : {state.timestamp}")
        print(f"  SOC             : {state.soc:.1%}")
        print(f"  battery_voltage : {state.battery_voltage:.2f} V")
        print(f"  battery_current : {state.battery_current:.2f} A")
        print(f"  battery_temp    : {state.battery_temp:.1f} °C")
        print(f"  solar_power_w   : {state.solar_power_w:.0f} W")
        print(f"  ac_load_w       : {state.ac_load_w:.0f} W")
    except StateUnavailableError as exc:
        print(f"  UNAVAILABLE: {exc}")
        state = None
    print()

    print("[solar forecast]")
    provider = SolarForecastProvider(config.forecast)
    forecast = provider.get()
    if forecast is None:
        print("  UNAVAILABLE (computepi unreachable or data too old)")
    else:
        now = datetime.now()
        upcoming = [e for e in forecast.entries if e.time >= now][:6]
        print(f"  fetched_at : {forecast.fetched_at.strftime('%Y-%m-%d %H:%M')}")
        print(f"  next {len(upcoming)} hours:")
        for e in upcoming:
            print(f"    {e.time.strftime('%H:%M')}  "
                  f"mppt150={e.mppt150_w:6.0f}W  "
                  f"mppt100={e.mppt100_w:6.0f}W  "
                  f"total={e.total_w:6.0f}W")
    print()

    if state is None:
        print("[projection] skipped — no current state")
        return

    print("[battery projection]")
    projector = BatteryProjector(config)
    projection = projector.project(state, forecast)
    print(f"  {'hour':>4}  {'time':>5}  {'solar_w':>8}  {'load_w':>7}  {'SOC':>6}")
    print(f"  {'----':>4}  {'----':>5}  {'-------':>8}  {'------':>7}  {'---':>6}")
    for i, h in enumerate(projection.hours):
        print(f"  {i+1:>4}  "
              f"{h.time.strftime('%H:%M'):>5}  "
              f"{h.solar_w:>8.0f}  "
              f"{h.estimated_load_w:>7.0f}  "
              f"{h.projected_soc:>6.1%}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Battery control unit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print state, forecast and projection then exit")
    args = parser.parse_args()

    config = ControlConfig.load_or_default(CONFIG_PATH)

    if args.dry_run:
        _print_dry_run(config)
        return

    run_loop(config)


if __name__ == "__main__":
    main()
