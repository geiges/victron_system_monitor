# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Victron System Monitor is a Python application for Venus OS that logs solar/inverter/battery data via D-Bus and runs a battery SOC (state-of-charge) estimator using an Extended Kalman Filter with a Thevenin circuit model.

## Running

```bash
uv run dbus_logger.py          # Main entry point - starts data logging loop
```

Requires Venus OS with D-Bus access to Victron devices. No test framework or linter is currently configured.

## Package Management

Uses **uv** (Astral) with `pyproject.toml`. Python 3.12+ required.

```bash
uv sync                        # Install dependencies
uv venv --system-site-packages --python /usr/bin/python3  # Venus OS setup
```

Runtime dependencies: numpy, pydbus. Analysis scripts also use pandas, matplotlib, pint (not in pyproject.toml).

## Architecture

**Data flow:** `dbus_logger.py` → polls D-Bus every 5 seconds → writes daily CSV files (`data/log_YY-MM-DD.csv`) → optionally updates SOC estimator.

### Core modules

- **dbus_logger.py** — Main loop. Discovers components, retrieves D-Bus values, writes CSV, triggers SOC updates. Handles CSV header migration when variables change.
- **components.py** — `BaseComponent` base class with `VictronSystem`, `VictronSolarCharger`, `VictronMultiplusII`. Each defines `component_variables` (list of `VariableType` namedtuples) and discovers its D-Bus interface via `com.victronenergy.*`.
- **config_default.py** — Configuration: log interval, timezone, component list, measurement calibration (cable resistances, voltage offsets). Creates `Power_system` instance.
- **power_system.py** — Dict-like wrapper for accessing components by short name.

### SOC estimation (Kalman filter pipeline)

- **SOC_estimator.py** — Orchestrator. `Measurement` class corrects raw voltage/current from multiple sources. Coordinates battery model + Kalman filter on 60-second intervals.
- **battery.py** — Thevenin equivalent circuit model (OCV + R0 + R1//C1). OCV-SOC via degree-5 polynomial. Tracks capacity in Coulombs via coulomb counting.
- **kalman.py** — Extended Kalman Filter. State: `[SOC, RC_voltage]`. Adaptive noise covariance based on current magnitude.
- **utils.py** — Simple polynomial class for OCV model evaluation and derivatives.

### Analysis scripts (not part of runtime)

- **soc_model.py** / **soc_test_model.py** — Offline SOC model validation over historical CSV data with plotting.
- **analysis.py** — Power flow analysis and cable resistance calculations.

## Key Patterns

- Components register D-Bus paths as `VariableType` namedtuples with `(dbus_device, address, label)`.
- Voltage measurements are corrected for cable drops: `V_corrected = V_raw - R_cable * I + offset` (per-component config in `config_default.py`).
- CSV files auto-rotate daily. If new variables appear, old data is backed up to `*_previous_data` and headers regenerated.
- Battery model state (`actual_capacity`, `RC_voltage`) persists across Kalman update cycles within a session.
