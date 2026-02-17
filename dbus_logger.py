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
from utils import File_Logger

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

    data = dict()
    for var_name, var_conf in variables_to_log.items():

        if debug:
            print(f'Getting {var_conf["address"]} from { var_conf["dbus_device"]}')
        var_value = bus.get(
            var_conf["dbus_device"],
            var_conf["address"]
            ).GetValue()

        try:
            if var_name not in config.non_numeric_var:
                var_value = round(var_value,config.round_digits)
            data[var_name] = var_value
        except Exception:
            print(f'Failed to read  {var_conf["address"]} from { var_conf["dbus_device"]}')
    return data



def update_loop(debug=False):
    
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

        simulator = simulation.System_Simulation(config.batt_config_V1)
        
    else:
        simulator = None



    t_now = datetime.now(tz=timezone)
    
    meas_logger = File_Logger("data/log_{date_str}.csv",
                                    config)
    sim_logger = File_Logger("data/sim_{date_str}.csv",
                                    config)
    
    
    

    while True:

        t_now = datetime.now(tz=timezone) # current date and time
        #now_str = t_now.strftime("%H:%M:%S")

        try:
            data = retrieve_data(bus, variables_to_log, debug)
            
        except Exception as E:
            data = None
            if debug:
                print(f"Exception {E} was raised.")
                print("Skipping this update loop")

        if data is not None:
            
            row_data = meas_logger.log_step(t_now, data)
            
            if  simulate_system:
                sim_row = simulator.update(raw_data=row_data,
                                           t_now = t_now,
                                           psystem=psystem)
                
                for key, var_value in sim_row.items():
                    
                    if key == 'time':
                        continue
                    sim_row[key] = round(var_value, config.round_digits)
                
                sim_logger.log_step(t_now, sim_row)
        
        print(f"Timestep done in {(datetime.now(tz=timezone) - t_now).total_seconds():2.2f}s")
  
        t_calc =  datetime.now(tz=timezone) - t_now


        time.sleep(max(0, config.log_interval - t_calc.total_seconds()))
        

def main(debug=False):
    os.makedirs("data", exist_ok=True)
    update_loop(debug=debug)


if __name__ == '__main__':
    main(debug=False)
