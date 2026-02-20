#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan  2 17:53:44 2026

@author: and
"""
import os
import time
import shutil
import pathlib
import csv
import pytz
from csv import DictWriter, DictReader
from pydbus import SystemBus
from utils import File_Logger, str2datetime, datetime2str
from datetime import datetime, timedelta

import config_default as config
import power_system

timezone = pytz.timezone(config.tz)

simulate_system = config.simulate_system

class Logger_Daily_aggregates():
    
    def __init__(self, config):
        
        self.cfg = config
        
        self.cfg = dict(
            fieldnames = ['date', 'solar_yield'],
            output_dir = 'data/daily/',
            input_dir  = 'data')
        
        self.cfg["out_filepath"] = os.path.join(
            self.cfg["output_dir"], 'solar_daily.csv')
        
        if not os.path.exists(self.cfg["out_filepath"]):
            self._init_output_file()
            
        self.last_date_str = self._get_last_date_logged()
        
        os.makedirs(self.cfg['output_dir'],exist_ok=True)
        
    def _get_last_date_logged(self):
        
        if not os.path.exists(self.cfg["out_filepath"]):
            return "NaT"
        
        with open(self.cfg["out_filepath"], mode="r") as fid:
            	data = fid.readlines() 
        lastRow = data[-1]
        
        last_date_str =  lastRow.split(',')[0]
        return last_date_str
    
    def _compute_day_yield(self, file):
        path = pathlib.Path(file)
        date_str = path.name.replace('log_','').replace('.csv','')
        filepath = os.path.join(self.cfg['input_dir'], file)
        assert os.path.exists(filepath)
        with open(filepath, mode="r") as fid:
            reader = DictReader(fid)
            first = next(reader)
            
            for row in reader:
                pass
            print(row)
            last = row
            
            data = dict(
                date = date_str,
                solar_yield = round(
                    float(last['mppt150/total_yield']) - float(first['mppt150/total_yield']),
                    config.round_digits
                    )
                )
            print(f"{first['mppt150/power_yield']} - {last['mppt150/power_yield']} = {data['solar_yield']}")
        return data
        
    
    def _init_output_file(self):
        files = sorted(x for x in os.listdir(self.cfg["input_dir"]) 
                       if (x.startswith('log') and (x.endswith('.csv')))
                       )
        
        with open(self.cfg["out_filepath"], mode="w") as fid_out:
            writer = DictWriter(fid_out, self.cfg["fieldnames"])
            writer.writeheader()
            for file in files:
                data = self._compute_day_yield(file)
                writer.writerow(data)
                
                
        
    def update_daily_aggregates(self, date_str):
        
        if self.last_date_str != date_str:
            
            time_delta = str2datetime(date_str) - str2datetime(self.last_date_str)
            base = str2datetime(self.last_date_str)
            date_list = [base + timedelta(days=x) for x in range(1, time_delta.days)]
            
            with open(self.cfg["out_filepath"], mode="a") as fid_out:
                writer = DictWriter(fid_out, self.cfg["fieldnames"])
                for date in date_list:
                    filepath  = "log_{date_str}.csv".format(date_str=datetime2str(date))
                    data = self._compute_day_yield(filepath)
                    writer.writerow(data)
                pass
        
        

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

   



    t_now = datetime.now(tz=timezone)
    
    meas_logger = File_Logger("data/log_{date_str}.csv",
                                    config)
    sim_logger = File_Logger("data/sim_{date_str}.csv",
                                    config)
    
    daily_logger =Logger_Daily_aggregates(config)
    
    
    if simulate_system:
        import simulation

        simulator = simulation.System_Simulation(config.batt_config_V1)
        
        curr_output_file = sim_logger.get_output_file_path(t_now)
        if False: #os.path.exists(curr_output_file):
            with open(curr_output_file, 'r') as fid:
                reader = csv.DictReader(fid)
                
                for row in reader:
                    #print(row)
                    soc = row['SOC_counted']
                    t_previous = row['time']
                    
        
        
            t_prev = datetime.strptime(t_previous, config.time_format)
            
            t_previous = datetime(year = t_now.year, month = t_now.month, day = t_now.day,
                                  hour = t_prev.hour, minute = t_prev.minute, second=t_prev.second)
            
            localtz = pytz.timezone(config.tz)
            t_previous = localtz.localize(t_previous)
    
            simulator.set_state(float(soc), t_previous )
            simulator.initilized = True

    else:
        simulator = None

    while True:

        t_now = datetime.now(tz=timezone) # current date and time
        date_str =  t_now.strftime(config.date_format)

        try:
            data = retrieve_data(bus, variables_to_log, debug)
            
        except Exception as E:
            data = None
            if debug:
                print(f"Exception {E} was raised.")
                print("Skipping this update loop")

        if data is not None:
            #date_str =  t_now.strftime(config.date_format)
            #daily_logger.update_daily_aggregates(date_str)
            
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
    # daily_logger =Logger_Daily_aggregates(config)

    # now = datetime.now(tz=timezone) # current date and time
    # date_str = now.strftime(config.date_format)

    # daily_logger.update_daily_aggregates(date_str)
