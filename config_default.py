#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan  2 17:31:27 2026

@author: and
"""
import components
date_format = "%y-%m-%d"
log_interval = 5 # seconds
round_digits = 3
tz = 'Europe/Berlin'


#systemsetup
system_components = [
    components.VictronSolarCharger('SmartSolar Charger MPPT 150/35', short_name='mppt150'),
    components.VictronMultplusII('MultiPlus-II 24/3000/70-32', short_name='multiplus'),
    components.VictronMultplusII('-', short_name='system'),
    ]


non_numeric_var = []

try:
    from config import *
    
except:
    print('Using default_config.py, create config.py for personal setup ')
    
    