import json
import pytest
from pathlib import Path
from flask import Flask

from control.api_routes import control_bp
from control.config import ControlConfig


@pytest.fixture
def app(tmp_path):
    test_app = Flask(__name__)
    test_app.config["CONTROL_DATA_DIR"] = tmp_path
    test_app.register_blueprint(control_bp, url_prefix="/control")
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


# --- GET /control/config ---

def test_get_config_returns_defaults(client):
    resp = client.get("/control/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["control_interval_seconds"] == 300
    assert data["safety_interval_seconds"] == 60
    assert data["battery"]["min_soc"] == pytest.approx(0.20)


def test_get_config_creates_yaml_file(client, tmp_path):
    client.get("/control/config")
    assert (tmp_path / "control_config.yaml").exists()


# --- PUT /control/config ---

def test_put_config_updates_top_level_field(client):
    resp = client.put("/control/config", json={"estimated_load_w": 350.0})
    assert resp.status_code == 200
    assert resp.get_json()["estimated_load_w"] == pytest.approx(350.0)


def test_put_config_persists_to_yaml(client, tmp_path):
    client.put("/control/config", json={"estimated_load_w": 250.0})
    cfg = ControlConfig.load(tmp_path / "control_config.yaml")
    assert cfg.estimated_load_w == pytest.approx(250.0)


def test_put_config_nested_update(client):
    resp = client.put("/control/config", json={"battery": {"min_soc": 0.20}})
    assert resp.status_code == 200
    assert resp.get_json()["battery"]["min_soc"] == pytest.approx(0.20)


def test_put_config_preserves_unmentioned_fields(client):
    client.put("/control/config", json={"estimated_load_w": 350.0})
    resp = client.put("/control/config", json={"horizon_hours": 12})
    data = resp.get_json()
    assert data["estimated_load_w"] == pytest.approx(350.0)
    assert data["horizon_hours"] == 12


def test_put_config_nested_preserves_sibling_keys(client):
    client.put("/control/config", json={"battery": {"min_soc": 0.20}})
    resp = client.put("/control/config", json={"battery": {"min_voltage": 23.0}})
    data = resp.get_json()
    assert data["battery"]["min_soc"] == pytest.approx(0.20)
    assert data["battery"]["min_voltage"] == pytest.approx(23.0)


def test_put_config_rejects_non_json(client):
    resp = client.put("/control/config", data="not json",
                      content_type="text/plain")
    assert resp.status_code == 400


# --- GET /control/schedule ---

def test_get_schedule_missing_file_returns_empty(client):
    resp = client.get("/control/schedule")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["actions"] == []
    assert data["created_at"] is None


def test_get_schedule_returns_file_content(client, tmp_path):
    payload = {"created_at": "2026-06-17T20:00:00", "actions": [
        {"actuator": "multiplus_mode", "value": 4,
         "execute_at": "2026-06-17T20:00:00", "reason": "low SOC", "agent": "system_safety"}
    ]}
    (tmp_path / "control_schedule.json").write_text(json.dumps(payload))
    resp = client.get("/control/schedule")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["actions"][0]["actuator"] == "multiplus_mode"


# --- GET /control/log ---

def test_get_log_empty_when_no_file(client):
    resp = client.get("/control/log")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_get_log_returns_entries(client, tmp_path):
    log_path = tmp_path / "control_log.jsonl"
    for i in range(10):
        with log_path.open("a") as f:
            f.write(json.dumps({"i": i}) + "\n")
    resp = client.get("/control/log?n=3")
    data = resp.get_json()
    assert len(data) == 3
    assert data[-1]["i"] == 9


def test_get_log_default_n_is_50(client, tmp_path):
    log_path = tmp_path / "control_log.jsonl"
    for i in range(60):
        with log_path.open("a") as f:
            f.write(json.dumps({"i": i}) + "\n")
    resp = client.get("/control/log")
    assert len(resp.get_json()) == 50


def test_get_log_invalid_n_returns_400(client):
    resp = client.get("/control/log?n=abc")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PUT /control/config — safety agent two-step disable guard
# ---------------------------------------------------------------------------

def test_put_config_disabling_safety_without_confirmed_disable_is_rejected(client):
    resp = client.put("/control/config", json={
        "agents": {"system_safety": {"enabled": False}}
    })
    assert resp.status_code == 400
    assert "confirmed_disable" in resp.get_json()["error"]


def test_put_config_disabling_safety_with_confirmed_disable_succeeds(client):
    resp = client.put("/control/config", json={
        "agents": {"system_safety": {"enabled": False, "confirmed_disable": True}}
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["agents"]["system_safety"]["enabled"] is False
    assert data["agents"]["system_safety"]["confirmed_disable"] is True


def test_put_config_enabling_safety_requires_no_confirmation(client):
    resp = client.put("/control/config", json={
        "agents": {"system_safety": {"enabled": True}}
    })
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PUT /control/config — wallbox agent group mutual exclusion
# ---------------------------------------------------------------------------

def test_put_config_enabling_forecast_wallbox_disables_soc_wallbox(client):
    resp = client.put("/control/config", json={
        "agents": {"forecast_wallbox": {"enabled": True}}
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["agents"]["forecast_wallbox"]["enabled"] is True
    assert data["agents"]["soc_wallbox_charge"]["enabled"] is False


def test_put_config_enabling_soc_wallbox_disables_forecast_wallbox(client):
    # First enable forecast_wallbox
    client.put("/control/config", json={
        "agents": {"forecast_wallbox": {"enabled": True}}
    })
    # Then switch to soc_wallbox_charge
    resp = client.put("/control/config", json={
        "agents": {"soc_wallbox_charge": {"enabled": True}}
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["agents"]["soc_wallbox_charge"]["enabled"] is True
    assert data["agents"]["forecast_wallbox"]["enabled"] is False


def test_put_config_non_wallbox_update_does_not_touch_group(client):
    # Set a known wallbox state first
    client.put("/control/config", json={
        "agents": {"forecast_wallbox": {"enabled": True}}
    })
    # Update an unrelated field
    resp = client.put("/control/config", json={"estimated_load_w": 123.0})
    assert resp.status_code == 200
    data = resp.get_json()
    # Group state unchanged from previous request
    assert data["agents"]["forecast_wallbox"]["enabled"] is True
    assert data["agents"]["soc_wallbox_charge"]["enabled"] is False
