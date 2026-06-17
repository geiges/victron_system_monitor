"""Flask blueprint for the control unit REST endpoints.

Routes
------
GET  /control/config        Return current ControlConfig as JSON.
PUT  /control/config        Partially update and persist ControlConfig.
GET  /control/schedule      Return current schedule (control_schedule.json).
GET  /control/log?n=50      Return last N log entries (control_log.jsonl).
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

    cfg_path = _data_dir() / "control_config.yaml"
    if cfg_path.exists():
        with open(cfg_path) as f:
            current = yaml.safe_load(f) or {}
    else:
        current = dataclasses.asdict(ControlConfig())

    _deep_update(current, body)

    try:
        updated = ControlConfig.from_dict(current)
    except Exception as exc:
        return jsonify({"error": f"Invalid config: {exc}"}), 400

    updated.save(cfg_path)
    return jsonify(dataclasses.asdict(updated))


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
    entries = DecisionLog(_data_dir() / "control_log.jsonl").tail(n)
    return jsonify(entries)


def _deep_update(base: dict, update: dict) -> None:
    """Recursively merge *update* into *base* in-place."""
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
