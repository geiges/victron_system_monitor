#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan  2 17:31:27 2026

@author: and
"""

date_format = "%y-%m-%d"
log_intervall = 10 # seconds
#systemsetup

mppt1 = "com.victronenergy.solarcharger.ttyUSB0"
inverter1 = "com.victronenergy.vebus.ttyUSB1"

# dbus variabls to be logged

variables_to_log = {
    "solar_power_1" : 
        {"dbus_device" : mppt1,
         "address" : "/Yield/Power",
         'unit' : "W"},
    "solar_cum_yield" : 
        {"dbus_device" : mppt1,
         "address" : "/Yield/System",
         "unit":"kWh"},
        }

non_numeric_var = []

try:
    from config import *
    
except:
    print('Using default_config.py, create config.py for personal setup ')
    
    