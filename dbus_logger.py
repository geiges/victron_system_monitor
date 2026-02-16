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

        config_V1 = {
            "Q_tot" : 210,
            "R0" : 0.01,
            "R1" : 0.04,
            "C1" : 2000,
            "time_step" : 60,
            "ncells" : 8,
            "R_var" : 0.5**2,   # measurement noise variance (V²)
            "Q_soc" : 1e-6,     # process noise for SOC state
            "Q_rc"  : 1e-6,     # process noise for RC voltage state
            "charge_efficiency" : 1.0,
            "version" : 'V1'
        }

        simulator = simulation.System_Simulation(config_V1)
        sim_initialized = False

    else:
        simulator = None
        sim_initialized = True

    def _write_headers(filename, fieldnames):
        with open(filename, mode="a") as fid:
            writer = DictWriter(fid, fieldnames)

            print(f"Writing head for new file {filename}")
            writer.writeheader()

    def _write_data(filename, fieldnames, row_data, date_str,  old_date_str):
        if data is not None:
            with open(filename, mode="a") as fid:
                

                if  date_str != old_date_str:
                    # new file was started we need to output the header
                    _write_headers(filename, fieldnames)
                


                
                # row.update(data)
                writer = DictWriter(fid, fieldnames)
                writer.writerow(row_data)
                print(f".done in {(datetime.now(tz=timezone) - t_now).total_seconds():2.2f}s")
        
    
    def _simulate_and_write_data_row(row_data, sim_initialized, t_now, date_str,  old_date_str, sim_filename):
        t_sim = datetime.now(tz=timezone)


        sim_row = simulator.update(raw_data=row_data,
                                   t_now = t_now,
                                   psystem=psystem)

        with open(sim_filename, mode="a") as fid:

            sim_fieldnames = sim_row.keys()
            writer = DictWriter(fid, sim_fieldnames)

            if  date_str != old_date_str:
                # new file was started we need to output the header
                _write_headers(sim_filename, sim_fieldnames)

            writer.writerow(sim_row)
            if debug:
                print(sim_row)
                print(t_now.strftime("%H:%M:%S"))
            print(f"Simulation done in {(datetime.now(tz=timezone) - t_sim).total_seconds():2.3f}s")


    # get variable_names from config
    fieldnames = (
        ["time"] + list(variables_to_log.keys())
        )

    t_now = datetime.now(tz=timezone)

    date_str = t_now.strftime("%y-%m-%d")
    filename = f"data/log_{date_str}.csv"
    
    old_date_str = update_existing_file(filename, fieldnames)
    
    #flag if day changed
    is_new_day = (old_date_str != date_str)
    old_data = None
    cached_data = None

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

            
        
        
        #print(data)
        row_data = dict(time=now_str)
        row_data.update(data)
        
        #flag if data dict is different from old 
        data_changed = (data != old_data)
        
        if config.logger_skip_no_changes and (data_changed or is_new_day):
            
            if cached_data is not None:
                print("Data changed in timestep {now_str} - writing out cached data for {cached_data['meas'][data']['time']")
                _write_data(**cached_data['meas'])
                _simulate_and_write_data_row(**cached_data['sim'])
            
            print(f"Writing data for  {row_data['time']}")    
            
            _write_data(filename, fieldnames, row_data, date_str,  old_date_str)
            if simulate_system and data is not None:
                _simulate_and_write_data_row(row_data, sim_initialized, t_now, date_str,  old_date_str, sim_filename)
                
            old_data = data
            cached_data = None
        else:
            
            print(f"Data for {now_str} is identical - not writing data data, caching data row.")
            cached_data = dict()
            cached_data['meas'] = dict(filename=filename, 
                                fieldnames=fieldnames, 
                                row_data = row_data.copy(),
                                date_str = date_str,  
                                old_date_str = old_date_str)
            
            
            cached_data['sim'] = dict(row_data=row_data,
                                      sim_initialized = sim_initialized,
                                      t_now = t_now,
                                      date_str = date_str,  
                                      old_date_str = old_date_str,
                                      sim_filename = sim_filename)
            old_data = data
            
            
        #replace old date string
        old_date_str = date_str
    
            
        t_calc =  datetime.now(tz=timezone) - t_now


        time.sleep(max(0, config.log_interval - t_calc.total_seconds()))



def main(debug=False):
    os.makedirs("data", exist_ok=True)
    update_loop(debug=debug)


if __name__ == '__main__':
    main(debug=True)
