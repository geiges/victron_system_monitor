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
    "R_var" : 0.5**2,   # measurement noise variance (V²)
    "Q_soc" : 1e-6,     # process noise for SOC state
    "Q_rc"  : 1e-6,     # process noise for RC voltage state
    "charge_efficiency" : 1.0,
    "version" : 'V1'
}



class System_Simulation():

    def __init__(self, sim_config, SOC, RC_voltage):



        self.R_var = sim_config['R_var']
        self.Q_soc = sim_config['Q_soc']
        self.Q_rc = sim_config['Q_rc']
        self.time_step = sim_config['time_step'] # in seconds

        # Battery properties
        self.R0 = sim_config['R0']
        self.R1 = sim_config['R1']
        self.C1 = sim_config['C1']
        self.ncells = sim_config['ncells']
        self.Q_tot = sim_config['Q_tot'] # in Ah

        #system_properties
        self.charge_efficiency = sim_config['charge_efficiency']


        self.battery_simulation = Battery(self.Q_tot,
                                          self.R0,
                                          self.R1,
                                          self.C1,
                                          self.ncells,
                                          self.charge_efficiency)

        self.set_state(SOC, RC_voltage)

    def estimate_initial_SOC(self, voltage):
        """
        Estimate initial SOC from an open-circuit voltage reading.
        Uses the inverse of the OCV-SOC polynomial by finding the SOC
        that minimizes |OCV(SOC) - voltage| within [0, 1].
        Best used when battery current is near zero.
        """
        from scipy.optimize import minimize_scalar
        result = minimize_scalar(
            lambda soc: (self.battery_simulation.OCV_model(soc) - voltage) ** 2,
            bounds=(0, 1),
            method='bounded'
        )
        return float(result.x)

    def set_state(self, SOC, RC_voltage= 0):
        print(f'Setting state to SOC={SOC} and RC_voltage={RC_voltage}')
        self.battery_simulation.actual_capacity =  SOC* self.battery_simulation.total_capacity

        print('setting up Kalman filter')
        self.Kf = ExtendedKalmanFilter(
                          self.R_var,
                          self.Q_soc,
                          self.Q_rc,
                          self.battery_simulation)

        self.Kf.set_state(SOC, RC_voltage)


    def update(self,
               raw_data,
               time_delta,
               psystem):

        battery_current_var = 'system/battery_current'
        battery_voltage_var = 'system/battery_voltage'

        ## coulomb counting
        sim_data = dict(time=raw_data['time'])

        # Simulate currents
        # reduce by const consumption for each component
        total_const_consumption = 0.

        non_system_variables = [x for x in raw_data.keys() if  not x.startswith('system')]

        for var in [x for x in non_system_variables if x.endswith('current')]:
            # get compenent name and comp from varible name
            comp = psystem[var.split('/')[0]]
            sim_data[var] = raw_data[var] - comp.const_consumption
            total_const_consumption +=  comp.const_consumption


        # total battery current
        sim_data[battery_current_var] = raw_data[battery_current_var] - total_const_consumption



        # Simulate voltages
        voltages_to_average = []
        for var in [x for x in non_system_variables if x.endswith('voltage')]:

            # get compenent name and comp from varible name
            comp = psystem[var.split('/')[0]]

            # current variable that relates to the voltage variable
            curr_var = var.replace('voltage', 'current')

            current_value = raw_data[curr_var] if curr_var in raw_data.keys() else 0

            # use component method to correct for cable losses and offsets
            sim_data[var] = comp.voltage_measurement(
                raw_data[var],
                current_value)

            voltages_to_average.append(sim_data[var])

        sim_data[battery_voltage_var] = sum(voltages_to_average) / len(voltages_to_average)

        # simulate SOC

        if time_delta is not None:
            self.battery_simulation.update(-time_delta, sim_data[battery_current_var])





        # ENKF updating
        if time_delta is not None:
            self.Kf.predict(time_delta=time_delta,
                            u=sim_data[battery_current_var])

        OCV_est = sim_data[battery_voltage_var] - self.R0 * sim_data[battery_current_var]
        if time_delta is not None:
            self.Kf.update(OCV_est, sim_data[battery_current_var])

        # updating counted SOC if Kf updated indicated full battery
        # and battery current is below 5A
        if (self.Kf.x[0,0] > 1.0) and  (abs(sim_data[battery_current_var]) < 5.):
            battery_simulation.set_state_of_charge(SOC=1.0)

        # updating counted SOC if Kf updated indicated empty battery
        # and battery current is below 5A
        if (self.Kf.x[0,0] < 0.0) and  (abs(sim_data[battery_current_var]) < 5.):
            battery_simulation.set_state_of_charge(SOC=0.0)


        estimated_SOC = float(self.Kf.x[0,0])

        SOC_counted = self.battery_simulation.state_of_charge
        sim_data['OCV_est'] = OCV_est
        sim_data['SOC_Kf'] = estimated_SOC
        sim_data['SOC_counted'] = SOC_counted
        return sim_data
