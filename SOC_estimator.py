#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 23 19:48:12 2026

@author: and
"""

# import sys
# import os
# import subprocess
# import matplotlib.pyplot as plt
import numpy as np
from battery import Battery
from kalman import ExtendedKalmanFilter


# system config
config_V1 = {
    "Q_tot" : 210,
    "R0" : 0.01,
    "R1" : 0.04,
    "C1" : 2000,
    "time_step" : 60,
    "ncells" : 8,
    "std_dev" : 0.01,
    "charge_efficiency" : 1.0,
    'system_consuption' : 5, # in W
    "version" : 'V1'
}


measurement_config ={
    "R_cabel_mppt" : 0.011,
    "R_cable_inverter": 0.0035,
    "mppt_voltage_offset": -0.1,
    "inverter_voltage_offset" : -0.16}

class Measurement():
    
    def __init__(self, 
                 R_cabel_mppt ,
                 R_cable_inverter,
                 mppt_voltage_offset,
                 inverter_voltage_offset,
                 system_consuption):
        
        self.R_cabel_mppt = R_cabel_mppt
        self.R_cable_inverter = R_cable_inverter
        self.mppt_voltage_offset = mppt_voltage_offset
        self.inverter_voltage_offset = inverter_voltage_offset
        self.system_consuption = system_consuption
        
        
    def corrected_battery_voltage(self, 
                current_mppt,
                voltage_mppt,
                inverter_current,
                voltage_inverter):
        
        
        #out = dict()
        
        current_mppt = current_mppt - (self.system_consuption / voltage_mppt)
        estimated_voltage = 0
        n_est= 0
        if np.isnan(voltage_mppt):
            
            estimated_voltage += voltage_mppt - (self.R_cabel_mppt * current_mppt) + self.mppt_voltage_offset
            n_est+=1
        if np.isnan(voltage_inverter):
                
            estimated_voltage += voltage_inverter - (self.R_cable_inverter * inverter_current) + self.mppt_voltage_offset
            n_est+=1
             
        if n_est > 0:
             est_battery_voltage = (estimated_voltage / n_est )
        
        return est_battery_voltage, current_mppt
    
    def corrected_battery_current(self, 
                                  voltage_mppt,
                                  battery_current,
                                  battery_power,
                                  battery_voltage
                                  ):
        
       if np.isnan(battery_current):

        battery_current = battery_power / battery_voltage



        # corretion for hidden constant consumers
        # const_consumption = 8   # W

        #df.solar_current_mppt = df.solar_current_mppt + (const_consumption /  df.battery_voltage_mppt)
        df.battery_power -= const_consumption
        df.battery_current -= const_consumption / df['est_battery_voltage'] 


class SOC_estimator():
    
    def __init__(self, config):
        
        
        self.std_dev = 0.01
        self.time_step = config['time_step'] # in seconds

        # Battery properties
        self.R0 = config['R0']
        self.R1 = config['R1']
        self.C1 = config['C1']
        self.ncells = config['ncells']
        self.Q_tot = config['Q_tot'] # in Ah
        self.system_consuption =  config['system_consuption'] # in W
        
        #system_properties
        self.charge_efficiency = config['charge_efficiency']
        
        # 1initial_SOC = config['initial_SOC']
        
        
        self.battery_simulation = Battery(self.Q_tot, 
                                          self.R0, 
                                          self.R1, 
                                          self.C1, 
                                          self.ncells, 
                                          self.charge_efficiency)
        
    def estimate_initial_SOC(self, voltage):
        pass
    
    def set_state(self, SOC, RC_voltage= 0):
        
        self.battery_simulation.actual_capacity =  SOC* self.battery_simulation.total_capacity
    
        self.Kf = ExtendedKalmanFilter(
                          self.std_dev, 
                          self.time_step, 
                          self.battery_simulation)
        
        self.Kf.set_state(SOC, RC_voltage)
   

    def update(self,
               measured_battery_current,
               measured_voltage, 
               time_delta):
        
        ## coulomb counting
        
        self.battery_simulation.update(time_delta, 
                                       measured_battery_current)
        
        counted_SOC = self.battery_simulation.state_of_charge
        

        # ENKF updating
        self.Kf.predict(time_delta=time_delta, 
                        u=measured_battery_current)
        
        corrected_voltage = measured_voltage - self.R0 * measured_battery_current
        self.Kf.update(corrected_voltage, measured_battery_current)
        
        estimated_SOC = self.Kf.x[0,0]
        
        return estimated_SOC, counted_SOC        