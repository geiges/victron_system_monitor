# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Victron System Monitor is a Python application for Venus OS that logs solar/inverter/battery data via D-Bus, runs a battery SOC (state-of-charge) estimator using an Extended Kalman Filter with a Thevenin circuit model, and operates an automated battery control unit that adjusts the system based on SOC, solar forecasts, and safety limits.

## Running

```bash
uv run dbus_logger.py          # Main logger — polls D-Bus every 5 s, writes CSV + updates SOC
uv run control_runner.py       # Control loop — runs agents, executes scheduled actions
uv run control_runner.py --dry-run  # Print state/forecast/projection and exit
uv run rest_api_app.py         # REST API — exposes /control/* endpoints
```

D-Bus logging requires Venus OS. The control runner and REST API can run independently on any host with access to the data directory.

## Testing

```bash
uv run python -m pytest tests/         # Run all tests
uv run python -m pytest tests/ -q      # Quiet mode
```

Tests live in `tests/`. Pre-existing failures in `test_aggregation_logger.py` and `test_forecast.py` are known and unrelated to the control unit.

## Package Management

Uses **uv** (Astral) with `pyproject.toml`. Python 3.12+ required.

```bash
uv sync                        # Install dependencies
uv venv --system-site-packages --python /usr/bin/python3  # Venus OS setup
```

Runtime dependencies: numpy, pydbus. Analysis scripts also use pandas, matplotlib, pint (not in pyproject.toml).

## Architecture

**Data flow:** `dbus_logger.py` → polls D-Bus every 5 seconds → writes daily CSV files (`data/log_YY-MM-DD.csv`) → optionally updates SOC estimator → writes `data/state.json` for the control unit.

### Core data-logging modules

- **dbus_logger.py** — Main loop. Discovers components, retrieves D-Bus values, writes CSV, triggers SOC updates. Handles CSV header migration when variables change.
- **components.py** — `BaseComponent` base class with `VictronSystem`, `VictronSolarCharger`, `VictronMultiplusII`. Each defines `component_variables` (list of `VariableType` namedtuples) and discovers its D-Bus interface via `com.victronenergy.*`.
- **config_default.py** — Configuration: log interval, timezone, component list, measurement calibration (cable resistances, voltage offsets), and battery parameters (`batt_config_V1`). Creates `Power_system` instance.
- **power_system.py** — Dict-like wrapper for accessing components by short name.

### SOC estimation (Kalman filter pipeline)

- **SOC_estimator.py** — Orchestrator. `Measurement` class corrects raw voltage/current from multiple sources. Coordinates battery model + Kalman filter on 60-second intervals.
- **battery.py** — Thevenin equivalent circuit model (OCV + R0 + R1//C1). OCV-SOC via degree-5 polynomial. Tracks capacity in Coulombs via coulomb counting.
- **kalman.py** — Extended Kalman Filter. State: `[SOC, RC_voltage]`. Adaptive noise covariance based on current magnitude.
- **simulation.py** — `System_Simulation` class: wraps `Battery` + `ExtendedKalmanFilter` for real-time SOC estimation from raw D-Bus data. Used by `dbus_logger.py`.
- **utils.py** — Simple polynomial class for OCV model evaluation and derivatives.

### Control unit (`control/` package)

The control unit reads `data/state.json` (written by the logger), fetches a solar forecast, runs a set of agents that produce `ScheduledAction`s, arbitrates conflicts, and executes actions via D-Bus or HTTP.

**Entry point:** `control_runner.py`
- Safety agents run every `safety_interval_seconds` (default 60 s).
- Planning agents run every `control_interval_seconds` (default 300 s).
- Config is reloaded from disk each cycle so REST API edits take effect without restart.
- `projection` is initialized to `None`; cycles are skipped until the first successful projection.

**Config system:** `control/config.py`
- `BatteryConfig` — sources all fields from `batt_config_V1` in `config_default.py`, including safety bounds:
  - `min_voltage` / `max_voltage` — voltage safety limits (V)
  - `min_temp` / `max_temp` — temperature safety limits (°C)
  - `min_soc` — low-SOC cutoff
- `ControlConfig` — top-level dataclass persisted to `data/control_config.yaml`. Loaded via `ControlConfig.load_or_default()`.
- All config dataclasses support `from_dict()` / `.save()` for YAML round-trips.

**State:** `control/state.py`
- `CurrentState` dataclass — snapshot of live system values (SOC, voltage, current, temp, solar power, AC load).
- `read_current_state(data_dir)` — reads `data/state.json`; raises `StateUnavailableError` if missing or SOC unavailable.
- `minutes_at_full_soc()` — inspects the most recent `sim_*.csv` to compute how long SOC has been ≥ a threshold.

**Solar forecast:** `control/forecast.py`
- `HourlyEntry` — a single hourly solar power reading (mppt150_w + mppt100_w).
- `SolarForecast` — list of `HourlyEntry` sorted by time.
  - `get_hour(t)` — exact-match lookup by hour slot.
  - `get_power(t)` — **linearly interpolates** between adjacent hourly entries; clamps to nearest entry outside the range.
- `SolarForecastProvider` — fetches and caches the forecast (two CSV files from an HTTP endpoint). Falls back to a stale cache within `max_age_hours`.

**Projection:** `control/projection.py`
- Projects battery SOC forward using coulomb counting at **15-minute resolution** (`STEP_MINUTES = 15`).
- `_ceil_to_quarter(t)` — snaps a timestamp to the next 15-minute wall-clock boundary (seconds ignored). The first projection step always starts on a round :00/:15/:30/:45 mark.
- `BatteryProjector.project(current, forecast)` → `SystemProjection` containing a list of `ProjectedStep` objects, one per 15-minute interval.
- `SystemProjection.steps` — the projected timeline (not `.hours`; that name was retired).
- `save_projection_csv(projection, path)` — writes the step timeline to a CSV file.
- `min_soc_hour` / `max_soc_hour` in log entries are **fractional hours** computed from step timestamps, not step counts.

**Schedule and actuator:** `control/schedule.py`, `control/actuator.py`
- `ScheduledAction` — an action to execute at a given time: `actuator` (name), `value` (int), `reason`, `agent`.
- `Schedule` — ordered list of `ScheduledAction`s, saved to `data/control_schedule.json` each cycle.
- `execute_action()` dispatches to D-Bus (`dbus-send` subprocess) or HTTP (Tasmota smart plug). D-Bus service addresses are resolved from `data/system_configuration.yaml` written by the logger on startup.
- Known actuators: `multiplus_mode` (D-Bus, `/Mode`), `mppt100_load` (D-Bus, `/Load/State`), `wallbox_charge` (Tasmota HTTP).

**Decision log:** `control/decision_log.py`
- `DecisionLog` — appends JSON lines to `data/control_log.jsonl`.
- `build_log_entry()` — assembles a full cycle snapshot (state, forecast availability, projection summary, agent results, schedule).

**REST API:** `control/api_routes.py` (Flask blueprint, mounted at `/control`)
- `GET /control/config` — returns the current `ControlConfig` as JSON.
- `PUT /control/config` — partial deep-merge update with two enforced rules:
  1. **Safety agent protection:** setting `agents.system_safety.enabled = false` is rejected with HTTP 400 unless `agents.system_safety.confirmed_disable = true` is in the same request body.
  2. **Wallbox group:** `soc_wallbox_charge` and `forecast_wallbox` are mutually exclusive (`_AGENT_GROUPS`). Enabling either one automatically disables the other before saving.
- `GET /control/schedule` — current schedule JSON.
- `GET /control/log?n=50&agent=name` — tail of the decision log, optionally filtered by agent name.
- `GET /control/agents` — list of known agents with enabled state and last log result.

### Agent system (`control/agents/`)

**Base:** `control/agents/base.py`
- `BaseAgent` — abstract base. Subclasses set `name: str`, `fast_cycle: bool`, and implement `run(projection, config) → AgentResult`.
- `is_enabled(config)` — default looks up `config.agents.<name>.enabled`.
- `AgentResult` — `(agent_name, actions, rationale, metrics)`.

**Arbitration** (in `control_runner._arbitrate`): Safety agent actions always win. If a safety agent targets an actuator, all other agents' actions on that same actuator are dropped.

**Agents:**

- **`system_safety`** (`SystemSafetyAgent`, `fast_cycle=True`) — checks SOC, voltage (both min and max), and temperature (both min and max) against `BatteryConfig` limits each safety cycle. Any violation sets `multiplus_mode = mode_off`. Multiple violations are combined into a single action and a single rationale string.
  - `is_enabled()` is overridden: requires **both** `enabled=False` and `confirmed_disable=True` to actually disable the agent. Setting only `enabled=False` has no effect — this is intentional protection.
  - Metrics: `soc_margin`, `min_voltage_margin`, `max_voltage_margin`, `min_temp_margin`, `max_temp_margin`. All positive when within safe limits.

- **`soc_wallbox_charge`** (`SocWallboxChargeAgent`, `fast_cycle=True`) — controls the wallbox charger based on SOC thresholds. Turns wallbox ON after SOC has been ≥ `soc_on_threshold` for ≥ `soc_on_minutes`; turns OFF immediately if SOC < `soc_off_threshold`. Reads `sim_*.csv` via `minutes_at_full_soc()`.

- **`forecast_wallbox`** (`ForecastWallboxAgent`) — controls the wallbox based on solar forecast (not yet implemented beyond stub). Mutually exclusive with `soc_wallbox_charge` — see wallbox group above.

- **`time_based`** (`TimeBasedAgent`) — schedules multiplus on/off around sunrise/sunset times.

- **`forecast_aware`** — retired; replaced by `forecast_wallbox`.

**Wallbox agent group:** Only one wallbox agent may be enabled at a time. The REST API enforces mutual exclusion automatically. In the runner, only the enabled agent in the group produces actions; the other is skipped by `is_enabled()`.

### Auxiliary data sources

- **aux_components.py** — `BaseAuxComponent` and subclasses for non-D-Bus HTTP data sources.
- **aux_logger.py** — Standalone process that polls aux components on the same interval as the main logger and writes `data/aux_YY-MM-DD.csv`.

### Analysis scripts (not part of runtime)

- **soc_model.py** / **soc_test_model.py** — Offline SOC model validation over historical CSV data with plotting.
- **analysis.py** — Power flow analysis and cable resistance calculations.

## Key Patterns

- Components register D-Bus paths as `VariableType` namedtuples with `(dbus_device, address, label)`.
- Voltage measurements are corrected for cable drops: `V_corrected = V_raw - R_cable * I + offset` (per-component config in `config_default.py`).
- CSV files auto-rotate daily. If new variables appear, old data is backed up to `*_previous_data` and headers regenerated.
- Battery model state (`actual_capacity`, `RC_voltage`) persists across Kalman update cycles within a session.
- All battery safety thresholds (`min_voltage`, `max_voltage`, `min_temp`, `max_temp`, `min_soc`) live in `batt_config_V1` in `config_default.py` and are loaded into `BatteryConfig` at startup. Do not hard-code these values elsewhere.
- Projection step times are always snapped to 15-minute wall-clock boundaries. When iterating `SystemProjection.steps`, use `step.time` for the timestamp and `(step.time - projection.current.timestamp).total_seconds() / 3600` to get elapsed hours.
