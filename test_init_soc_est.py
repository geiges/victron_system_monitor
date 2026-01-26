#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jan 26 12:23:03 2026

@author: and
"""
import os
import datetime
import pytz
from csv import DictWriter, DictReader

import config_default as config


timezone = pytz.timezone(config.tz)
import SOC_estimator as soc

def get_last_files():
    
    # get last model output

    
    
    
    
    now = datetime.datetime.now(tz=timezone) # current date and time
    #today = datetime(*now.timetuple()[:3])
   
   
    days = -1
    last_log_file = None
    while True:
        days +=1
        date = now +datetime.timedelta(days=days)
        date_str =date.strftime("%y-%m-%d")
        log_filename = f"data/log_{date_str}.csv"
        output_filename = f"data/model_{date_str}.csv"
        
        if os.path.exists(log_filename):
            last_log_file = log_filename
            
            if os.path.exists(output_filename):
                return log_filename, output_filename
           
        else:
            if days > 0:
                print(Warning('No initial state found'))
                return last_log_file, None

def get_last_model_state():
    
    log_filename, output_filename = get_last_files()
    
    date_str = log_filename.replace('data/log_','').replace('.csv','')
    if output_filename is None:
        # run inital model for earliest log file
        print ('running initial model')
        output_filename = log_filename.replace('log','model')
        soc_model = soc.SOC_estimator(soc.config_V1)
        
        model_fields = ['battery_voltage_1',
                        'battery_voltage_2',
                        'est_battery_voltage',
                        'battery_current',
                        'estimated_SOC',
                        'counted_SOC',
                        'estimated_OCV',
                        'counted_OCV'
                        ]
        
        soc_model.set_state(SOC=.5, RC_voltage=0.0)
        measure = soc.Measurement(**soc.measurement_config)
        
        reader = DictReader(open(log_filename))
        columns = reader.fieldnames
        
        with open(output_filename, mode="w") as fid_out:
            writer = DictWriter(fid_out, model_fields)
            writer.writeheader()
            last_timestep = None
            for row in reader:
                if last_timestep is None:
                    last_timestep = datetime.datetime(date_str + ' ' + row['time'])
                    
                else:
                    
                    measured_voltage = measure.process_raw_measurments(current_mppt = row['solar_current_mppt'], 
                                                                       voltage_mppt = row['battery_voltage_mppt'], 
                                                                       inverter_current = row['inverter_dc_input_current'], 
                                                                       voltage_inverter = row['battery_voltage_inverter'])
                soc_model.C1
                
        
    else:
        # read last state
        pass

if __name__ == "__main__":
    # log_filename, output_filename = get_last_files()
    get_last_model_state()
    os.system('rm data/model_26-01-26.csv ')
    