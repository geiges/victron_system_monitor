#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auxiliary logger for non-D-Bus data sources.

Runs as a standalone process alongside dbus_logger.py. Polls all devices
declared in config.aux_components on the same interval as the main logger
and writes daily CSV files to data/aux_YY-MM-DD.csv.

When active components change (devices go offline / come back online), the
set of logged columns can change. On every timestep the logger checks whether
new keys have appeared and re-initialises the File_Logger if needed, which
backs up the existing file and rewrites it with the merged column set —
matching the behaviour of dbus_logger.py.
"""
import os
import time
import yaml
import pytz
from datetime import datetime

import config_default as config
from utils import File_Logger

timezone = pytz.timezone(config.tz)


def retrieve_aux_data(aux_components: list, debug: bool = False) -> dict:
    """
    Poll all aux components and merge their output into a single flat dict.

    Components that raise an exception are skipped with a warning; their
    variables are absent from the returned dict for this timestep.
    """
    data = {}
    for component in aux_components:
        try:
            if debug:
                print(f"Fetching {component.short_name} ({component.protocol})")
            data.update(component.get_labeled_data())
        except Exception as exc:
            print(f"Warning: {component} fetch failed — {exc}")
    return data


def _columns_expanded(data: dict, logger: File_Logger) -> bool:
    """
    Return True when data contains keys not yet tracked by the logger,
    meaning a new device has appeared and the CSV columns must grow.
    """
    if not logger.initialized or logger.fieldnames is None:
        return False
    current_keys = set(data.keys()) | {'time'}
    return not current_keys.issubset(set(logger.fieldnames))


def update_loop(debug: bool = False) -> None:
    aux_components = getattr(config, 'aux_components', [])

    if not aux_components:
        print("No aux_components configured in config. Exiting.")
        return

    aux_logger = File_Logger("data/aux_{date_str}.csv", config)

    now = datetime.now(tz=timezone)
    state = {'running_since': now.strftime("%y-%m-%d %H:%M")}

    while True:
        t_now = datetime.now(tz=timezone)

        data = retrieve_aux_data(aux_components, debug=debug)

        if data:
            if _columns_expanded(data, aux_logger):
                print(
                    "New columns detected (component came online) — "
                    "re-initialising logger file structure."
                )
                aux_logger.initialized = False

            row_data = aux_logger.log_step(t_now, data)

            if row_data is not None:
                state.update(row_data)
                with open('data/aux_state.yaml', 'w') as fp:
                    yaml.dump(state, fp, default_flow_style=False, allow_unicode=True)

        t_calc = datetime.now(tz=timezone) - t_now
        time.sleep(max(0.0, config.log_interval - t_calc.total_seconds()))


def main(debug: bool = False) -> None:
    os.makedirs("data", exist_ok=True)
    update_loop(debug=debug)


if __name__ == '__main__':
    main(debug=False)
