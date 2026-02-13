#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan  2 17:31:27 2026

@author: and
"""
import components
import power_system

#%%

date_format = "%y-%m-%d"
log_interval = 5 # seconds
round_digits = 3
tz = 'Europe/Berlin'

non_numeric_var = []


#system setup
_system_components = [
    components.VictronSystem(None, short_name='system'),
    components.VictronSolarCharger('SmartSolar Charger MPPT 150/35', short_name='mppt150'),
    components.VictronMultiplusII('MultiPlus-II 24/3000/70-32', short_name='multiplus'),
    ]

# system connectors (relevant for measurements)
measurement_components = {
    "mppt150": {
        'connector_R0' :  0.011,
        'voltage_offset' :  -0.1},
    "multiplus": {
        'connector_R0' :  0.0035,
        'voltage_offset' :  -0.16},
    }

power_system = power_system.Power_system(_system_components)

for component, measurement_setup in measurement_components.items():
    power_system[component].init_measurement_correction(**measurement_setup)
    

try:
    # try to import actual config file, failes if no personal file is found
    from config import *
    
except:
    print('Using default_config.py, create config.py for personal setup ')
    
    