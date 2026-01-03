#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Jan  3 16:14:47 2026

@author: and
"""

from pydbus import SystemBus
bus = SystemBus()

device = "com.victronenergy.vebus.ttyUSB1"
address = "/Dc/0/Temperature"

value = bus.get(
    device, 
    address
    ).GetValue()

print(f"Value for {address} on {device} is : {value}")