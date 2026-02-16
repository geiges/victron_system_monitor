#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan  2 17:53:44 2026

@author: and
"""
import os
import time
import shutil
# import pandas as pd
import csv
import config_default as config

from csv import DictWriter
from pydbus import SystemBus

from datetime import datetime, timedelta
import pytz

import power_system

timezone = pytz.timezone(config.tz)

simulate_system = config.simulate_system




def update_existing_file(filename: str,
                         fieldnames: list[str],) -> str:

    now = datetime.now(tz=timezone) # current date and time

    date_str = now.strftime(config.date_format)

    # date_str = pd.Timestamp.now().strftime(config.date_format)

    if not os.path.exists(filename):
        return 'NaT'

    tt = time.time()
    print("Loading from disk and extending with new columns..", end="")
    # df = pd.read_csv(filename, index_col=0)
    reader = csv.DictReader(open(filename))
    columns = reader.fieldnames
    # update file if new columns or new order

    # header is only updated if more fieldnames are not all in existing columns
    update_header = not set(fieldnames).issubset(set(columns))

    if update_header:
        #
        shutil.move(filename, filename + '_previous_data')
        reader = csv.DictReader(open(filename + '_previous_data'))
        with open(filename, mode="a") as f:
            writer = DictWriter(f, fieldnames)
            writer.writeheader()
            for row in reader:
                writer.writerow(row)


    print(f".done in {time.time() - tt:2.2f}s")

    return date_str

def retrieve_data(bus, variables_to_log, debug):

    data = list()
    for var_name, var_conf in variables_to_log.items():

        if debug:
            print(f'Getting {var_conf["address"]} from { var_conf["dbus_device"]}')
        var_value = bus.get(
            var_conf["dbus_device"],
            var_conf["address"]
            ).GetValue()

        try:
            var_value = round(var_value,config.round_digits)
            data.append((var_name, var_value))
        except Exception:
            print(f'Failed to read  {var_conf["address"]} from { var_conf["dbus_device"]}')
    return data


def update_loop(debug=False):


    t_previous = None
    if os.environ.get("VICTRON_TEST_SESSION_BUS"):
        from pydbus import SessionBus
        bus = SessionBus()
    else:
        bus = SystemBus()

    psystem = power_system.init_power_system(system_components = config.system_components,
                                             measurement_components=config.measurement_components
                                             )


    variables_to_log, missing_components = psystem.get_variables_to_log(bus)

    if simulate_system:
        import simulation

        config_V1 = {
            "Q_tot" : 210,
            "R0" : 0.01,
            "R1" : 0.04,
            "C1" : 2000,
            "time_step" : 60,
            "ncells" : 8,
            "std_dev" : 0.01,
            "charge_efficiency" : 1.0,
            'system_consuption' : 5, # in W
            "version" : 'V1'
        }

        simulator = simulation.System_Simulation(config_V1, SOC=0.5, RC_voltage=0.)
        sim_initialized = False

    else:
        simulator = None
        sim_initialized = True

    # get variable_names from config
    fieldnames = (
        ["time"] + list(variables_to_log.keys())
        )

    t_now = datetime.now(tz=timezone)

    date_str = t_now.strftime("%y-%m-%d")
    filename = f"data/log_{date_str}.csv"
    
    old_date_str = update_existing_file(filename, fieldnames)


    # wait until next full interval before first sync
    if not debug:
        time.sleep(max(0, config.log_interval - (t_now % timedelta(config.log_interval).total_seconds())))

    while True:

        t_now = datetime.now(tz=timezone) # current date and time

        now_str = t_now.strftime("%H:%M:%S")
        date_str =  t_now.strftime("%y-%m-%d",)
        filename = f"data/log_{date_str}.csv"
        sim_filename = f"data/sim_{date_str}.csv"
        try:
            data = retrieve_data(bus, variables_to_log, debug)
        except Exception as E:
            data = None
            if debug:
                print(f"Exception {E} was raised.")
                print("Skipping this update loop")

        if data is not None:
            with open(filename, mode="a") as fid:
                writer = DictWriter(fid, fieldnames)

                if  date_str != old_date_str:
                    # new file was started we need to output the header
                    print("Writing head for new file")
                    writer.writeheader()

                row = dict(time=now_str)

                # state = 0

                for var, value in data:


                    if var not in config.non_numeric_var:
                        try:
                            value = float(value)
                        except ValueError:
                            value = ""
                    row[var] = value

                    # if var in status_mapping:
                    #     exp = status_vars.index(var)
                    #     if value not in status_mapping[var].keys():
                    #         print(f"{var, value} not found")
                    #     state_part = status_mapping[var][value]
                    #     state += state_part * (10**exp)

                # code = str(state).zfill(len(status_vars))
                # row["status"] = code
                if debug:
                    print(row)
                    print(t_now.strftime("%H:%M:%S"))
                writer.writerow(row)
                print(f".done in {(datetime.now(tz=timezone) - t_now).total_seconds():2.2f}s")


        if simulate_system and data is not None:

            t_sim = datetime.now(tz=timezone)

            if not sim_initialized:
                # Use first battery voltage reading to estimate initial SOC
                voltage_key = 'system/battery_voltage'
                current_key = 'system/battery_current'
                if voltage_key in row and current_key in row:
                    v = float(row[voltage_key])
                    i = float(row[current_key])
                    if abs(i) < 2.0:
                        initial_soc = simulator.estimate_initial_SOC(v)
                        print(f'Estimated initial SOC from OCV={v:.2f}V: {initial_soc:.2%}')
                        simulator.set_state(initial_soc, RC_voltage=0.)
                    else:
                        print(f'Current too high ({i:.1f}A) for OCV-based init, using default SOC=0.5')
                sim_initialized = True

            if t_previous is None:
                time_delta = None
            else:
                time_delta = (t_now - t_previous).total_seconds()
            sim_row = simulator.update(raw_data=row,
                                       time_delta=time_delta,
                                       psystem=psystem)

            with open(sim_filename, mode="a") as fid:

                sim_fieldnames = sim_row.keys()
                writer = DictWriter(fid, sim_fieldnames)

                if  date_str != old_date_str:
                    # new file was started we need to output the header
                    print("Writing head for new file")
                    writer.writeheader()

                writer.writerow(sim_row)
                if debug:
                    print(sim_row)
                    print(t_now.strftime("%H:%M:%S"))
                print(f"Simulation done in {(datetime.now(tz=timezone) - t_sim).total_seconds():2.3f}s")


        #replace old date string
        old_date_str = date_str

        t_previous = t_now
        t_calc =  datetime.now(tz=timezone) - t_now


        time.sleep(max(0, config.log_interval - t_calc.total_seconds()))



def main(debug=False):
    os.makedirs("data", exist_ok=True)
    update_loop(debug=debug)


if __name__ == '__main__':
    main(debug=True)
