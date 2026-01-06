#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan  2 17:31:27 2026

@author: and
"""

date_format = "%y-%m-%d"
log_interval = 5 # seconds
round_digits = 3
tz = 'Europe/Berlin'
#systemsetup

mppt1 = "com.victronenergy.solarcharger.ttyUSB0"
inverter1 = "com.victronenergy.vebus.ttyUSB1"
system = "com.victronenergy.system"

# dbus variabls to be logged

variables_to_log = {
    "solar_power_1" : 
        {"dbus_device" : mppt1,
         "address" : "/Yield/Power",
         'unit' : "W"},
    "battery_voltage_mppt" : 
            {"dbus_device" : mppt1,
             "address" : "/Dc/0/Voltage",
             "unit":"V"},
    "solar_current_mppt" : 
            {"dbus_device" : mppt1,
             "address" : "/Dc/0/Current",
             "unit":"V"},
    "solar_cum_yield" : 
        {"dbus_device" : mppt1,
         "address" : "/Yield/System",
         "unit":"kWh"},
    "battery_voltage_inverter" : 
            {"dbus_device" : inverter1,
             "address" : "/Dc/0/Voltage",
             "unit":"V"},
     "inverter_dc_input_power" : 
             {"dbus_device" : inverter1,
              "address" : "/Dc/0/Power",
              "unit":"W"},
     "inverter_dc_input_current" : 
             {"dbus_device" : inverter1,
              "address" : "/Dc/0/Current",
              "unit":"W"},
     "inverter_ac_output" : 
            {"dbus_device" : inverter1,
             "address" : "/Ac/Out/P",
             "unit":"W"},
    "battery_temperature" : 
                {"dbus_device" : inverter1,
                 "address" : "/Dc/0/Temperature",
                 "unit":"°C"},
    "inverter_alarm_temperature_status" : 
                {"dbus_device" : inverter1,
                 "address" : "/Alarms/TemperatureSensor",
                 "unit":""},     
    "inverter_alarm_overload" : 
                {"dbus_device" : inverter1,
                 "address" : "/Alarms/Overload",
                 "unit":""},   
    "battery_power" : 
            {"dbus_device" : system,
             "address" : "/Dc/Battery/Power",
             "unit":"W"},
     "battery_current" : 
             {"dbus_device" : system,
              "address" : "/Dc/Battery/Current",
              "unit":"V"},
        }

non_numeric_var = []

try:
    from config import *
    
except:
    print('Using default_config.py, create config.py for personal setup ')
    
    