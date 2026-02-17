"""
Integration test: start mock_dbus_service, then verify that the logger's
discovery and data-retrieval logic reads back the values from a CSV file.
"""
import csv
import os
import subprocess
import sys
import time
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
MOCK_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "mock_dbus_service.py")
CSV_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "log_testing.csv")


def _wait_for_bus_name(bus, name, timeout=10):
    """Poll until *name* appears on the session bus."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if name in bus.dbus.ListNames():
            return True
        time.sleep(0.2)
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mock_service():
    """Start the mock D-Bus service as a subprocess and tear it down after."""
    proc = subprocess.Popen(
        [sys.executable, "-u", MOCK_SCRIPT, CSV_FILE],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # Give the service time to register on the bus
    from pydbus import SessionBus
    bus = SessionBus()
    ready = _wait_for_bus_name(bus, "com.victronenergy.system")
    if not ready:
        proc.kill()
        out, _ = proc.communicate(timeout=3)
        pytest.fail(f"Mock service did not start in time.\n{out.decode()}")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="module")
def session_bus():
    from pydbus import SessionBus
    return SessionBus()


@pytest.fixture(scope="module")
def csv_first_row():
    """Return the first data row of the input CSV as a dict."""
    with open(CSV_FILE, newline="") as f:
        reader = csv.DictReader(f)
        return next(reader)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_discovery(mock_service, session_bus):
    """All three Victron bus names are discoverable on the session bus."""
    names = session_bus.dbus.ListNames()
    assert "com.victronenergy.system" in names
    assert "com.victronenergy.solarcharger.ttyUSB0" in names
    assert "com.victronenergy.vebus.ttyUSB1" in names


def test_product_names(mock_service, session_bus):
    """ProductName returns the correct string for each device."""
    solar = session_bus.get(
        "com.victronenergy.solarcharger.ttyUSB0", "/ProductName"
    ).GetValue()
    assert solar == "SmartSolar Charger MPPT 150/35"

    vebus = session_bus.get(
        "com.victronenergy.vebus.ttyUSB1", "/ProductName"
    ).GetValue()
    assert vebus == "MultiPlus-II 24/3000/70-32"


def test_component_discovery(mock_service, session_bus):
    """The power_system component discovery finds all three components."""
    import config_default as config
    import power_system

    psystem = power_system.init_power_system(
        system_components=config.system_components,
        measurement_components=config.measurement_components,
    )
    variables_to_log, missing = psystem.get_variables_to_log(session_bus)

    assert len(missing) == 0, f"Missing components: {missing}"
    assert len(variables_to_log) == 13


def test_retrieve_data_matches_csv(mock_service, session_bus, csv_first_row):
    """Retrieved D-Bus values match the first row of the input CSV."""
    import config_default as config
    import power_system
    import dbus_logger

    psystem = power_system.init_power_system(
        system_components=config.system_components,
        measurement_components=config.measurement_components,
    )
    variables_to_log, _ = psystem.get_variables_to_log(session_bus)
    retrieved_data = dbus_logger.retrieve_data(session_bus, variables_to_log, debug=False)

    for col_name, expected_str in csv_first_row.items():
        if col_name == "time":
            continue
        expected = round(float(expected_str), config.round_digits)
        actual = retrieved_data[col_name]
        assert actual == expected, (
            f"{col_name}: expected {expected}, got {actual}"
        )
