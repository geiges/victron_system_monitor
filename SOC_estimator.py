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




class SOC_estimator():
    
    def __init__(self, config, SOC, RC_voltage):
        
        
        self.std_dev = 0.01
        
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
        
        self.set_state(SOC, RC_voltage)
        
    def estimate_initial_SOC(self, voltage):
        #TODO
        pass
    
    def set_state(self, SOC, RC_voltage= 0):
        print(f'Setting state to SOC={SOC} and RC_voltage={RC_voltage}')
        self.battery_simulation.actual_capacity =  SOC* self.battery_simulation.total_capacity
    
        print('setting up Kalman filter')
        self.Kf = ExtendedKalmanFilter(
                          self.std_dev, 
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