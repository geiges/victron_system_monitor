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
time_format = "%H:%M:%S"
log_interval = 5 # seconds
round_digits = 3
tz = 'Europe/Berlin'

non_numeric_var = []
simulate_system = True
logger_skip_no_changes = True

#system setup
system_components = [
    components.VictronSystem(None, short_name='system'),
    components.VictronSolarCharger('SmartSolar Charger MPPT 150/35',
                                   short_name='mppt150',
                                   const_consumption=0.2),
    components.VictronMultiplusII('MultiPlus-II 24/3000/70-32',
                                  short_name='multiplus',
                                  const_consumption=0.1),
    components.VictronPhoenix24_800('Phoenix Inverter 24V 800VA 230V', 
                                    short_name='phoenix',
                                    const_consumption=0.1)
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

# Battery Simulation configuration
batt_config_V1 = {
    "Q_tot" : 210,
    "R0" : 0.01,
    "R1" : 0.04,
    "C1" : 2000,
    "ncells" : 8,
    "R_var" : 0.5**2,   # measurement noise variance (V²)
    "Q_soc" : 1e-6,     # process noise for SOC state
    "Q_rc"  : 1e-6,     # process noise for RC voltage state
    "charge_efficiency" : 1.0,
    "version" : 'V1'
}

try:
    # try to import actual config file, failes if no personal file is found
    from config import *

except ImportError:
    print('Using default_config.py, create config.py for personal setup ')
