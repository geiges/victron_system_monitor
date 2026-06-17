# Battery Control Unit — Architecture Plan

## Context

The project already logs solar/battery data every 5 seconds via `dbus_logger.py` (Victron D-Bus) and `aux_logger.py` (Tasmota/DEYE HTTP). A Kalman-filtered SOC estimate is produced in `simulation.py`. The REST API (`ecowhen_data_api`, port 5100) serves CSV logs and can toggle device modes via D-Bus commands. Solar forecasts are produced on a separate machine (`computepi`) by the `ecowhen_homesolar` workflow and served via the ecowhen_data_api on that machine.

The goal is a **control unit** that projects the battery state forward using the solar forecast, runs independent agents to produce a schedule, executes it autonomously, logs agent reasoning, and exposes config/log/schedule via REST API.

---

## High-Level Architecture

```
[dbus_logger / simulation] → data/state.json + sim_*.csv   (this machine)
[computepi:5100/files/homesolar/] → forecast_solar_yield_*.csv  (network)
           ↓
     control/runner.py (every N minutes, configurable)
           ↓
     ┌────────────────────────────────────────────────────┐
     │  StateReader → CurrentState                        │
     │  ForecastProvider → SolarForecast (or None)        │
     │  BatteryProjection → SystemProjection              │
     │         ↓                                          │
     │  Agent: SystemSafety  → immediate safety actions   │
     │  Agent: TimeBased     → sunrise/sunset schedule    │
     │  Agent: ForecastAware → day-ahead plan (if forecast available) │
     │         ↓                                          │
     │  Arbitrator → merged Schedule                      │
     │         ↓                                          │
     │  Actuator → D-Bus toggle commands                  │
     │         ↓                                          │
     │  DecisionLog → data/control_log.jsonl              │
     └────────────────────────────────────────────────────┘
           ↓
     REST API: /control/config, /control/schedule, /control/log
```

---

## Module Structure

```
control/
├── __init__.py
├── runner.py          # Main loop: state → forecast → project → agents → act → log
├── state.py           # CurrentState dataclass; reads data/state.json + latest sim CSV
├── forecast.py        # SolarForecastProvider: HTTP GET from computepi; returns None if unavailable; runs only once per hour
├── projection.py      # BatteryProjector: wraps Battery from battery.py; projects SOC forward and battery net flow
├── schedule.py        # Schedule + ScheduledAction dataclasses; JSON-serializable
├── actuator.py        # D-Bus command wrapper via dbus-send
├── decision_log.py    # JSONL appender + last-N reader → data/control_log.jsonl
├── config.py          # ControlConfig pydantic model; load/save data/control_config.yaml
└── agents/
    ├── base.py              # BaseAgent ABC: run(projection, config) → AgentResult
    ├── system_safety.py     # Real-time safety: monitors SOC/voltage/temperature, cuts AC if limits exceeded
    ├── time_based.py        # Sunrise/sunset schedule using pvlib to connect the AC inverter
    └── forecast_aware.py    # Day-ahead plan using SystemProjection (inactive if forecast is None)

tests/
├── test_state.py       # CurrentState parsing (mock state.json + sim CSV)
├── test_forecast.py    # SolarForecastProvider (mock HTTP responses)
├── test_projection.py  # BatteryProjector (known solar/load inputs → expected SOC trajectory)
├── test_agents.py      # Each agent with synthetic SystemProjection inputs
└── test_actuator.py    # D-Bus command generation (without hardware)
```

Entry point: `control_runner.py` (top-level standalone process, like `aux_logger.py`).

---

## Key Data Structures

### CurrentState (control/state.py)
Snapshot of present system state. Source: `data/state.json` + latest sim CSV row.
```python
@dataclass
class CurrentState:
    timestamp: datetime
    soc: float              # Kalman-filtered SOC (0–1), from sim CSV
    battery_voltage: float  # V
    battery_current: float  # A (positive = charging)
    battery_temp: float     # °C
    solar_power_w: float    # W total (mppt150 + mppt100)
    ac_load_w: float        # W (multiplus AC output)
    inverter_mode: int      # D-Bus value: 3=on, 4=inverter-only
    mppt100_load_on: bool   # DC load switch state
```

### SolarForecast (control/forecast.py)
Hourly solar power forecast per array, fetched from computepi via HTTP.
```python
@dataclass
class HourlyEntry:
    time: datetime
    mppt150_w: float
    mppt100_w: float
    total_w: float

@dataclass
class SolarForecast:
    fetched_at: datetime
    entries: list[HourlyEntry]   # hourly, covering configured horizon

class SolarForecastProvider:
    # Returns SolarForecast on success, None if computepi unreachable or files stale
    def get(self) -> SolarForecast | None: ...
```

Fetches two CSV files from `http://<computepi_url>/files/homesolar/`:
- `forecast_solar_yield_5312439980_mppt150.csv` (columns: `time`, `0`)
- `forecast_solar_yield_5312439980_mppt100.csv`

Cached in memory; re-fetched when age exceeds `forecast_cache_minutes` (config). If HTTP fails or data is >N hours old, returns `None`.

### SystemProjection (control/projection.py)
Forward simulation of battery SOC over the planning horizon using the existing `Battery` class from `battery.py`.

```python
@dataclass
class ProjectedHour:
    time: datetime
    solar_w: float           # from SolarForecast (0 if forecast unavailable)
    estimated_load_w: float  # from config (constant for now)
    projected_soc: float     # from Battery.state_of_charge after update

@dataclass
class SystemProjection:
    current: CurrentState
    forecast: SolarForecast | None   # None → ForecastAware agent skips
    horizon_hours: int
    hours: list[ProjectedHour]

class BatteryProjector:
    def __init__(self, config):
        self._battery = Battery(Q_tot=config.battery.capacity_ah, ...)
    
    def project(self, current: CurrentState, forecast: SolarForecast | None,
                config: ControlConfig) -> SystemProjection:
        self._battery.set_state_of_charge(current.soc)
        hours = []
        for h in range(config.horizon_hours):
            t = current.timestamp + timedelta(hours=h+1)
            solar_w = forecast.get_hour(t) if forecast else 0.0
            load_w = config.estimated_load_w
            net_current = (solar_w - load_w) / self._battery.OCV  # A, + = charging
            self._battery.update(-3600, net_current)  # sign convention from simulation.py
            hours.append(ProjectedHour(time=t, solar_w=solar_w,
                                       estimated_load_w=load_w,
                                       projected_soc=self._battery.state_of_charge))
        return SystemProjection(current=current, forecast=forecast,
                                horizon_hours=config.horizon_hours, hours=hours)
```

**Reuse note**: `Battery.update(time_delta, current)` uses the same sign convention as `simulation.py` (passing `-time_delta`, positive current = charging). The RC transient decays to ~0 within minutes (R1·C1 = 80 s), so at hourly resolution its effect is negligible for projection. The Kalman filter (`kalman.py`) is NOT used for projection — it's only needed when correcting against real voltage measurements.

---

## Agent Descriptions

### Agent 1: SystemSafety (always enabled, highest priority)
Real-time safety guardian — reacts to measured state, not forecast:
- If `soc < config.min_soc`: disable inverter + disable mppt100 DC load immediately
- If `battery_voltage < config.min_voltage`: same
- If `battery_temp > config.max_temp`: disable charging (MPPT modes off)
- Always reports current margin: `{"soc_margin": soc - min_soc, "voltage_margin": V - min_V}`
- Safety actions cannot be overridden by other agents (arbitrator gives them highest priority)

### Agent 2: TimeBased
Schedule inverter on/off around sunrise/sunset (computed via pvlib using lat/lon from existing config):
- Enable inverter ~30 min before sunset → use battery through night
- Disable inverter ~30 min after sunrise → solar takes over
- Can be disabled entirely via config

### Agent 3: ForecastAware
Day-ahead optimizer — uses `SystemProjection.hours` to plan discharge:
- **Skips entirely if `projection.forecast is None`** (no fallback, just inactive)
- At each cycle, reads projected SOC trajectory → identifies depletion risk
- Outputs schedule: enable/disable inverter/load at specific hours to optimally spread discharge
- Example: "SOC at dawn projected to be 45%, enable inverter from 20:00–01:00 then pause"
- Horizon and scheduling scope (current day / multi-day) controlled by config; TBD which default

---

## ControlConfig (control/config.py)

```yaml
control_interval_seconds: 300
horizon_hours: 24           # simulation/planning window; TBD if single-day or multi-day
estimated_load_w: 200       # constant load estimate for projection (until load model exists)

forecast:
  computepi_base_url: "http://192.168.1.X:5100"   # fill in actual IP
  endpoint_id: "homesolar"
  mppt150_file: "forecast_solar_yield_5312439980_mppt150.csv"
  mppt100_file: "forecast_solar_yield_5312439980_mppt100.csv"
  cache_minutes: 60
  max_age_hours: 6    # if files older than this, treat forecast as unavailable

battery:
  capacity_wh: 5040   # 210 Ah × 24 V nominal
  min_soc: 0.15
  min_voltage: 22.5   # V
  max_temp: 45.0      # °C

agents:
  system_safety:
    enabled: true     # cannot be disabled via API (enforced by runner)
  time_based:
    enabled: false
    inverter_on_before_sunset_min: 30
    inverter_off_after_sunrise_min: 30
  forecast_aware:
    enabled: false
    # horizon_hours inherited from top-level

actuators:
  multiplus_mode: true
  mppt100_load: true
```

---

## REST API Extensions

Add `/control/*` blueprint to `ecowhen_data_api` (same port 5100 on the Victron Pi):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/control/config` | Current ControlConfig as JSON |
| PUT | `/control/config` | Update config (pydantic-validated; runner reloads on next cycle) |
| GET | `/control/schedule` | Planned ScheduledActions from `data/control_schedule.json` |
| GET | `/control/log?n=50` | Last N entries from `data/control_log.jsonl` |
| GET | `/control/agents` | Agent list with enabled state + last AgentResult |

Decision log entry format:
```json
{
  "timestamp": "2026-06-17T19:30:00",
  "current": {"soc": 0.72, "battery_voltage": 25.4, "ac_load_w": 380, "solar_power_w": 45},
  "forecast_available": true,
  "projected_soc_at_dawn": 0.18,
  "agents": [
    {
      "name": "system_safety",
      "rationale": "SOC 72% above min 15%. Voltage 25.4V above min 22.5V. Temp 28°C below max 45°C. No safety action.",
      "actions": [],
      "metrics": {"soc_margin": 0.57, "voltage_margin": 2.9}
    },
    {
      "name": "forecast_aware",
      "rationale": "Projected SOC at dawn: 18%, below target 25%. Scheduling inverter off at 02:00 to preserve charge.",
      "actions": [{"execute_at": "2026-06-18T02:00:00", "actuator": "multiplus_mode", "value": 4}],
      "metrics": {"projected_soc_at_dawn": 0.18}
    }
  ],
  "schedule": [{"execute_at": "2026-06-18T02:00:00", "actuator": "multiplus_mode", "value": 4, "agent": "forecast_aware"}]
}
```

---

## Actuator Details

Phase 1 actuators, called via `dbus-send`:

| Actuator | D-Bus service | Path | Values |
|----------|--------------|------|--------|
| `multiplus_mode` | `com.victronenergy.vebus.ttyUSB2` | `/Mode` | 3 (on), 4 (inverter-only) |
| `mppt100_load` | `com.victronenergy.solarcharger.ttyUSB1` | `/LoadOutputState` | 0 (off), 1 (on) |

`/LoadOutputState` path needs confirmation on the actual device (standard VictronEnergy path). Actuator reads current value before writing to skip no-op commands.

---

## Venus OS / Platform Constraints

The control unit runs on Venus OS (Victron's embedded Linux). Current runtime Python packages are **only `numpy` and `pydbus`**. All other packages must either be stdlib or verified installable on the target system.

| Need | Stdlib alternative | Package to test |
|------|-------------------|-----------------|
| HTTP client (forecast fetch) | `urllib.request` (stdlib) | `requests` (if installable) |
| YAML config load/save | `PyYAML` — already used by dbus_logger | verify on Venus OS |
| Config validation | Manual dataclass validation | `pydantic` — NOT tested yet |
| CSV parsing | `csv` module (stdlib) | avoid `pandas` |
| Sunrise/sunset | Simple astronomical formula (pure Python, no deps) | `pvlib` — NOT tested yet |
| JSON log | `json` (stdlib) | — |

**Rule**: implement Phase 1 using only stdlib + numpy + PyYAML. Pydantic and pvlib require explicit installation testing on Venus OS before use. Replace `pydantic` with manual YAML→dataclass parsing for now. Replace pvlib sunrise/sunset with a lightweight pure-Python formula (e.g. based on NOAA algorithm or similar).

**Before using any new package**: test `pip install <package>` on the Venus OS device and verify no native build dependencies fail.

---

## Phase 1 Scope (implement first)

### Step 1: Data links
- `CurrentState` from `data/state.json` + latest `sim_YY-MM-DD.csv` row
- `SolarForecastProvider` — HTTP GET from computepi (URL in config); returns `None` if unreachable
- `BatteryProjector.project(current, forecast, config)` → `SystemProjection`
- Test with `--dry-run`: print current state, forecast (or "unavailable"), projected SOC trajectory

### Step 2: Config + runner skeleton
- `ControlConfig` dataclass loaded from `data/control_config.yaml` via PyYAML; manual field validation (no pydantic on Venus OS); write default YAML if missing
- `control_runner.py` main loop: load config → read state → get forecast → project → run agents → log → sleep

### Step 3: SystemSafety agent + decision log
- Implement `SystemSafety` fully (SOC/voltage/temp checks → immediate D-Bus actions)
- Stub `TimeBased` and `ForecastAware` (return no actions, rationale = "not yet implemented")
- Append JSONL entry to `data/control_log.jsonl` each cycle

### Step 4: REST API endpoints
- `GET/PUT /control/config`, `GET /control/schedule`, `GET /control/log` in ecowhen_data_api
- Serve `data/control_schedule.json` and `data/control_log.jsonl` files

### Tests (written alongside each step)
- `tests/test_projection.py` — `BatteryProjector`: constant solar in → SOC increases; zero solar + load → SOC decreases at expected rate; SOC clamps at 0/1
- `tests/test_state.py` — `CurrentState` fields from fixture files (no real D-Bus needed)
- `tests/test_forecast.py` — mock `requests.get` → verify `HourlyEntry` list; HTTP error → verify returns `None`
- `tests/test_agents.py` — `SystemSafety` with SOC below threshold → inverter disable action; normal state → no action

### Deferred to Phase 2
- Full `TimeBased` and `ForecastAware` agents
- Load forecasting (history-based average load)
- Multi-day scheduling horizon decision
- Web UI

---

## Decisions Locked In

| Topic | Decision |
|-------|----------|
| Forecast fallback | None — if unavailable, `ForecastAware` agent is simply inactive |
| Forecast source | HTTP GET from computepi (`ecowhen_homesolar` REST API, port 5100); URL configurable |
| Battery projection | Reuse `Battery` class from `battery.py`; energy balance per hour; Kalman filter not used |
| Safety agent | `SystemSafety` monitors SOC + voltage + temperature; highest arbitration priority |
| REST API | Extend `ecowhen_data_api` with `/control/*` blueprint on same port 5100 |
| Phase 1 actuators | `multiplus` inverter mode + `mppt100` DC load switch |
| Scheduling horizon | Configurable `horizon_hours`; single-day vs multi-day TBD |
| Tests | pytest, written alongside each implementation step |

---

## Open Items

- **computepi IP**: Fill in `forecast.computepi_base_url` before first run
- **mppt100 DC load D-Bus path**: Confirm `/LoadOutputState` on actual device
- **Scheduling horizon**: Decide single-day vs multi-day default

---

## Verification

1. `uv run control_runner.py --dry-run` — prints `SystemProjection` and agent rationale, no D-Bus writes
2. Check `data/control_log.jsonl` for well-formed JSONL with agent reasoning
3. `curl http://localhost:5100/control/log?n=5` — verify JSON response
4. `curl -X PUT http://localhost:5100/control/config -d '{"agents":{"system_safety":{"enabled":true}}}'` — verify config reloads
5. Set low battery values in test fixture → verify `SystemSafety` triggers correct D-Bus action
