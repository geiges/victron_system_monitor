#!/usr/bin/env python3
"""Convert old-format CSV log files to new column naming convention.

Reads log_*.csv files from data/ directory, applies column renaming,
drops unused columns, and writes converted files in-place.

Backs up each original file to <filename>.bak before overwriting.
"""

import csv
import shutil
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Old column name -> New column name (None = drop)
COLUMN_MAP = {
    "time": "time",
    "solar_power_1": "power_yield_mppt150",
    "battery_voltage_mppt": "battery_voltage_mppt150",
    "solar_current_mppt": "battery_current_mppt150",
    "solar_cum_yield": "total_yield_mppt150",
    "battery_voltage_inverter": "battery_voltage_multiplus",
    "inverter_dc_input_power": None,  # drop
    "inverter_dc_input_current": "battery_current_multiplus",
    "inverter_ac_output": "ac_power_output_multiplus",
    "battery_temperature": "battery_temperature_system",
    "inverter_alarm_temperature_status": "alarm_temperature_multiplus",
    "inverter_alarm_low_battery": "alarm_low_battery_multiplus",
    "inverter_alarm_overload": "alarm_overload_multiplus",
    "battery_power": None,  # drop
    "battery_current": "battery_current_system",
}

# New header order (must match logger_update output)
NEW_HEADER = [
    "time",
    "power_yield_mppt150",
    "battery_voltage_mppt150",
    "battery_current_mppt150",
    "total_yield_mppt150",
    "ac_power_output_multiplus",
    "battery_voltage_multiplus",
    "battery_current_multiplus",
    "alarm_temperature_multiplus",
    "alarm_low_battery_multiplus",
    "alarm_overload_multiplus",
    "battery_voltage_system",
    "battery_current_system",
    "battery_temperature_system",
]


def convert_file(filepath: Path) -> bool:
    """Convert a single CSV file. Returns True if converted, False if skipped."""
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        old_fields = reader.fieldnames

        if old_fields is None:
            print(f"  SKIP (empty): {filepath.name}")
            return False

        # Already in new format
        if old_fields[0] == "time" and "power_yield_mppt150" in old_fields:
            print(f"  SKIP (already converted): {filepath.name}")
            return False

        # Check that we recognise the header
        unknown = set(old_fields) - set(COLUMN_MAP)
        if unknown:
            print(f"  SKIP (unknown columns {unknown}): {filepath.name}")
            return False

        rows = list(reader)

    # Build converted rows
    new_rows = []
    for row in rows:
        new_row = {}
        for old_col, value in row.items():
            new_col = COLUMN_MAP[old_col]
            if new_col is not None:
                new_row[new_col] = value
        # battery_voltage_system = copy of battery_voltage_multiplus
        new_row["battery_voltage_system"] = new_row.get("battery_voltage_multiplus", "")
        new_rows.append(new_row)

    # Backup original
    backup = filepath.with_suffix(".csv.bak")
    shutil.copy2(filepath, backup)

    # Write converted file
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NEW_HEADER)
        writer.writeheader()
        writer.writerows(new_rows)

    print(f"  OK: {filepath.name} ({len(new_rows)} data rows, backup -> {backup.name})")
    return True


def main():
    files = sorted(DATA_DIR.glob("log_*.csv"))
    if not files:
        print("No log files found in data/")
        return

    print(f"Found {len(files)} log file(s) in {DATA_DIR}")
    converted = 0
    for f in files:
        if convert_file(f):
            converted += 1

    print(f"\nDone: {converted} file(s) converted.")


if __name__ == "__main__":
    main()
