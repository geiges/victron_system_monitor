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

timezone = pytz.timezone(config.tz)

parallel_SOC = True

def get_variables_to_log(dbus):
    
    variables_to_log = dict()
    missing_components = list()
    
    #loop over configures system components
    for component in config.system_components:
        
        if component.is_avaiable_on_bus(dbus):
            # component is currently connected
            variables_to_log.update(component.get_device_variables(dbus))
        else:
            missing_components.append(component)
            
    if len(missing_components)> 0:
        print(f'The following components are unresponsive: {missing_components}')
    return variables_to_log, missing_components
            

def update_existing_file(filename: str, 
                         fieldnames: list[str],
                         soc_model,
                         measure) -> str:

    now = datetime.now(tz=timezone) # current date and time

    date_str = now.strftime(config.date_format)

    # date_str = pd.Timestamp.now().strftime(config.date_format)
    
    if not os.path.exists(filename):
        return 

    tt = time.time()
    print("Loading from disk and extending with new columns..", end="")
    # df = pd.read_csv(filename, index_col=0)
    reader = csv.DictReader(open(filename))
    columns = reader.fieldnames
    # update file if new columns or new order
    changed_columns = set(fieldnames) != set(columns)
    if changed_columns:
        #
        shutil.move(filename, filename + '_previous_data')
        reader = csv.DictReader(open(filename + '_previous_data'))
        with open(filename, mode="a") as f:
            writer = DictWriter(f, fieldnames)
            writer.writeheader()
            for row in reader:
                writer.writerow(row)
        
        # df.reindex(columns=fieldnames[1:]).to_csv(filename)
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
        except:
            print(f'Failed to read  {var_conf["address"]} from { var_conf["dbus_device"]}')
    return data


def update_loop(debug=False):
    
    bus = SystemBus()
    
    variables_to_log = get_variables_to_log(bus)
    
    if parallel_SOC:
        import SOC_estimator as soc
        
        soc_model = soc.SOC_estimator(soc.config_V1)
        measure = soc.Measurement(**soc.measurement_config)
    else:
        soc_model, measure = None, None
        
    # get variable_names from config
    fieldnames = (
        ["time"] + list(variables_to_log.keys())
        )
        
    now = datetime.now(tz=timezone)
    
    date_str = now.strftime("%y-%m-%d")
    filename = f"data/log_{date_str}.csv"
    update_existing_file(filename, fieldnames, soc_model, measure)
    
    
    if not os.path.exists(filename):
        write_header = True
    else:
        write_header= False
    
    
    
    # wait until next full interval before first sync
    if not debug:
        time.sleep(config.log_interval - (now % timedelta(config.log_interval).total_seconds()))

    while True:
        now = datetime.now(tz=timezone) # current date and time

        now_str = now.strftime("%H:%M:%S")
        date_str =  now.strftime("%y-%m-%d",)
        filename = f"data/log_{date_str}.csv"
        try:
            data = retrieve_data(bus, variables_to_log, debug)
        except Exception as E:
            data = None
            if debug:
                print(f"Exception {E} was raised.")
                print("Skipping this update loop")
        
        if data is not None:
            with open(filename, mode="a") as f:
                writer = DictWriter(f, fieldnames)
                if write_header:
                    # new file was started we need to output the header
                    writer.writeheader()
                    write_header = False
    
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
                    print(now.strftime("%H:%M:%S"))
                writer.writerow(row)
                print(f".done in {(datetime.now(tz=timezone) - now).total_seconds():2.2f}s")

        t_calc =  datetime.now(tz=timezone) - now
        #t_calc = time.time() - now
        time.sleep(config.log_interval - t_calc.total_seconds())



def main(debug=False):
    os.makedirs("data", exist_ok=True)
    update_loop(debug=debug)
    
    
if __name__ == '__main__':
    main(debug=True)