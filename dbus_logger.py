#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan  2 17:53:44 2026

@author: and
"""
import os 
import time
# import pandas as pd
import csv
import config_default as config

from csv import DictWriter
from pydbus import SystemBus
    
from datetime import datetime


def update_existing_file(filename: str, fieldnames: list[str]) -> str:

    now = datetime.now() # current date and time

    date_str = now.strftime(config.date_format)

    # date_str = pd.Timestamp.now().strftime(config.date_format)
    
    if not os.path.exists(filename):
        return "startup"

    tt = time.time()
    print("Loading from disk and extending with new columns..", end="")
    # df = pd.read_csv(filename, index_col=0)
    reader = csv.DictReader(open(filename))
    columns = reader.fieldnames
    # update file if new columns or new order
    changed_columns = any([c1 != c2 for c1,c2 in zip(columns, fieldnames)])
    if changed_columns:
        raise (Exception('Columns did change, not yet implemented'))
        
        # df.reindex(columns=fieldnames[1:]).to_csv(filename)
    print(f".done in {time.time() - tt:2.2f}s")

    return date_str

def retrieve_data(bus, variables_to_log):
    
    data = list()
    for var_name, var_conf in variables_to_log.items():
        
        var_value = bus.get(
            var_conf["dbus_device"], 
            var_conf["address"]
            ).GetValue()
        
        var_value = round(var_value,config.round_digits)
        data.append((var_name, var_value))
    return data


def update_loop(debug=False):
    
    
    bus = SystemBus()

    # get variable_names from config
    fieldnames = (
        ["time"] + list(config.variables_to_log.keys())
        )
        
    now = time.time()
    
    date_str = time.strftime("%y-%m-%d", time.localtime(now))
    filename = f"data/log_{date_str}.csv"
    old_date_str = update_existing_file(filename, fieldnames)

    # wait until next full interval before first sync
    if not debug:
        time.sleep(config.log_interval - (time.localtime().tm_sec % config.log_interval))

    while True:
        now = time.time()
        now_str = time.strftime("%H:%M:%S", time.localtime(now))
        date_str = time.strftime("%y-%m-%d", time.localtime(now))
        filename = f"data/log_{date_str}.csv"

        data = retrieve_data(bus, config.variables_to_log)
        
        with open(filename, mode="a") as f:
            writer = DictWriter(f, fieldnames)
            if date_str != old_date_str:
                # new file was started we need to output the header
                writer.writeheader()
                old_date_str = date_str

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
                print(time.time())
            writer.writerow(row)
            print(f".done in {time.time() - now:2.2f}s")

        t_calc = time.time() - now
        time.sleep(config.log_interval - t_calc)



def main(debug=False):
    os.makedirs("data", exist_ok=True)
    update_loop(debug=debug)
    
    
if __name__ == '__main__':
    main(debug=True)