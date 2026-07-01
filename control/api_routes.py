"""Flask blueprint for the control unit REST endpoints.

Routes
------
GET  /control/config           Return current ControlConfig as JSON.
PUT  /control/config           Partially update and persist ControlConfig.
GET  /control/schedule         Return current schedule (control_schedule.json).
GET  /control/sequence         Return active sequence status (sequence_status.json).
POST /control/sequence/abort   Abort the active sequence (writes abort flag for runner).
POST /control/sequence/start   Manually start a named sequence (writes start flag for runner).
GET  /control/sequences        List available sequence names.
GET  /control/log?n=50         Return last N log entries (control_log.jsonl).
GET  /control/log?agent=name   Filter entries by agent name.
GET  /control/agents           Return all agents with enabled state + last result.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import yaml
from flask import Blueprint, current_app, jsonify, request

from control.config import ControlConfig
from control.decision_log import DecisionLog

control_bp = Blueprint("control", __name__)


def _data_dir() -> Path:
    return current_app.config.get("CONTROL_DATA_DIR", Path("data"))


@control_bp.get("/config")
def get_config():
    cfg = ControlConfig.load_or_default(_data_dir() / "control_config.yaml")
    return jsonify(dataclasses.asdict(cfg))


@control_bp.put("/config")
def put_config():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "JSON object required"}), 400

    # Guard: disabling system_safety requires an explicit confirmed_disable flag
    safety_update = body.get("agents", {}).get("system_safety", {})
    if safety_update.get("enabled") is False and not safety_update.get("confirmed_disable"):
        return jsonify({
            "error": (
                "Disabling system_safety requires confirmed_disable: true "
                "in the same request."
            )
        }), 400

    cfg_path = _data_dir() / "control_config.yaml"
    if cfg_path.exists():
        with open(cfg_path) as f:
            current = yaml.safe_load(f) or {}
    else:
        current = dataclasses.asdict(ControlConfig())

    _deep_update(current, body)

    # Enforce wallbox agent group: enabling one disables all others in the same group
    agents_update = body.get("agents", {})
    for group in _AGENT_GROUPS:
        for name in group:
            if agents_update.get(name, {}).get("enabled") is True:
                for other in group:
                    if other != name:
                        current.setdefault("agents", {}).setdefault(other, {})["enabled"] = False
                break  # only one winner per group per request

    try:
        updated = ControlConfig.from_dict(current)
    except Exception as exc:
        return jsonify({"error": f"Invalid config: {exc}"}), 400

    updated.save(cfg_path)
    return jsonify(dataclasses.asdict(updated))


@control_bp.get("/sequence")
def get_sequence():
    path = _data_dir() / "sequence_status.json"
    if not path.exists():
        return jsonify({"status": "none"})
    with open(path) as f:
        return jsonify(json.load(f))


@control_bp.post("/sequence/abort")
def abort_sequence():
    flag = _data_dir() / "sequence_abort.flag"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.touch()
    return jsonify({"aborted": True})


@control_bp.post("/sequence/start")
def start_sequence():
    body = request.get_json(silent=True) or {}
    name = body.get("sequence_name", "")
    from control.sequences import SEQUENCES
    if name not in SEQUENCES:
        return jsonify({"error": f"unknown sequence {name!r}"}), 400
    flag = _data_dir() / "sequence_start.json"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(json.dumps({"sequence_name": name}))
    return jsonify({"started": name})


@control_bp.get("/sequences")
def list_sequences():
    from control.sequences import SEQUENCES
    return jsonify(list(SEQUENCES.keys()))


@control_bp.get("/schedule")
def get_schedule():
    path = _data_dir() / "control_schedule.json"
    if not path.exists():
        return jsonify({"created_at": None, "actions": []})
    with open(path) as f:
        return jsonify(json.load(f))


@control_bp.get("/log")
def get_log():
    try:
        n = int(request.args.get("n", 50))
    except (ValueError, TypeError):
        return jsonify({"error": "n must be an integer"}), 400

    agent_filter = request.args.get("agent")
    fetch_n = n if not agent_filter else n * 20
    entries = DecisionLog(_data_dir() / "control_log.jsonl").tail(fetch_n)

    if agent_filter:
        entries = [e for e in entries if isinstance(e, dict) and e.get("agent") == agent_filter][-n:]

    return jsonify(entries)


# Agents that are mutually exclusive: enabling one disables the others in the same group.
_AGENT_GROUPS: list[list[str]] = [
    ["soc_wallbox_charge", "forecast_wallbox"],
]

_KNOWN_AGENTS = ["system_safety", "time_based", "soc_wallbox_charge", "forecast_wallbox"]


@control_bp.get("/agents")
def get_agents():
    cfg = ControlConfig.load_or_default(_data_dir() / "control_config.yaml")
    agents_dict = dataclasses.asdict(cfg.agents)

    entries = DecisionLog(_data_dir() / "control_log.jsonl").tail(500)

    last_results: dict = {}
    for entry in reversed(entries):
        if isinstance(entry, dict) and "agent" in entry:
            name = entry["agent"]
            if name not in last_results:
                last_results[name] = entry
            if len(last_results) >= len(_KNOWN_AGENTS):
                break

    return jsonify([
        {
            "name": name,
            "enabled": agents_dict.get(name, {}).get("enabled", True),
            "last_result": last_results.get(name),
        }
        for name in _KNOWN_AGENTS
    ])


def _deep_update(base: dict, update: dict) -> None:
    """Recursively merge *update* into *base* in-place."""
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
