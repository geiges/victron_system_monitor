#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Feb 12 17:04:18 2026

@author: and
"""
from typing import NamedTuple

class VariableType(NamedTuple):
    basename :str
    subaddress : str
    unit : str


class BaseComponent(object):
    """
    Base class for system components to provide some common functions
    """
    
    def __init__(self, product_name):
        # Root string to identify available components on dbus
        self.component_type = None
        
    def _components_on_bus(self, dbus):
        """
        Check is type of device is available on bus and returns instances
        """    
        return [x for x in dbus.dbus.ListNames() if x.startswith(self.component_type)]
    
    def is_avaiable_on_bus(self, dbus):
    
        for interface in self._components_on_bus(dbus):
            
            if self.product_name == dbus.get(
                interface, 
                '/ProductName'
                ).GetValue():
                    return True
        
        return False
    
    def get_interface(self, dbus):
        """
        Get the interface for actual product. Return None if not available
        """
        
        for interface in self._components_on_bus(dbus):
            
            comp_product_name = dbus.get(
                interface, 
                '/ProductName'
                ).GetValue()
            
            if comp_product_name == self.product_name:
                
                return interface
        else:
            return None
        
    def get_device_variables(self,dbus):
        """
        Returns a dictionary of all implemented variables for this device
        """
        interface_address = self.get_interface(dbus)
        variables = {}
        if interface_address is None:
            return variables
        else:
            for variable in self.component_variables:
                
                variables.update({
                    f"{variable.basename}_{self.short_name}": {
                        "dbus_device" : interface_address,
                        "address" : variable.subaddress,
                        'unit' : variable.unit},
                    })
            return variables
        

class VictronSystem(BaseComponent):
    """
    Victron solar charger component
    """
    component_variables =[
        VariableType(basename = "battery_voltage", subaddress = "/Dc/Battery/Voltage", unit='V'), 
        VariableType(basename = "battery_current", subaddress = "/Dc/Battery/Current", unit='A'),
        VariableType(basename = "battery_temperature", subaddress = "/Dc/Battery/Temperature", unit='°C'),
        ]
    
    def __init__(self, product_name, short_name):
        self.product_name = product_name
        self.short_name = short_name
        self.component_type = 'com.victronenergy.system'
        
    
class VictronSolarCharger(BaseComponent):
    """
    Victron solar charger component
    """
    component_variables =[
        VariableType(basename = "power_yield", subaddress = "/Yield/Power", unit='W'),
        VariableType(basename = "battery_voltage", subaddress = "/Dc/0/Voltage", unit='V'), 
        VariableType(basename = "battery_current", subaddress = "/Dc/0/Current", unit='A'),
        VariableType(basename = "total_yield", subaddress = "/Yield/System", unit='kWh'),
        ]
    
    def __init__(self, product_name, short_name):
        self.product_name = product_name
        self.short_name = short_name
        self.component_type = 'com.victronenergy.solarcharger'
        
        
class VictronMultiplusII(BaseComponent):
    """
    Victron solar charger component
    """
    component_variables =[
        VariableType(basename = "ac_power_output", subaddress = "/Ac/Out/P", unit='W'),
        VariableType(basename = "battery_voltage", subaddress = "/Dc/0/Voltage", unit='V'), 
        VariableType(basename = "battery_current", subaddress = "/Dc/0/Current", unit='A'),
        VariableType(basename = "alarm_temperature", subaddress="/Alarms/TemperatureSensor", unit=''),
        VariableType(basename = "alarm_low_battery", subaddress="/Alarms/LowBattery", unit=''),
        VariableType(basename = "alarm_overload", subaddress="/Alarms/Overload", unit='')
        ]
    
    def __init__(self, product_name, short_name):
        self.product_name = product_name
        self.short_name = short_name
        self.component_type = 'com.victronenergy.vebus'
        

        
        

            
            
if __name__ == "__main__":
    #testing
    mppt = VictronSolarCharger('SmartSolar Charger MPPT 150/35', short_name='mppt150')
    inverter = VictronMultplusII('MultiPlus-II 24/3000/70-32', short_name='multiplus')
    system = VictronMultplusII('-', short_name='system')
