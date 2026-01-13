#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jan  6 19:32:23 2026

@author: and
"""
import sys
import os
import subprocess
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

sys.path.append('/home/and/python/Battery-Kalman/Python/')
#%%
dates = [
    # "26-01-06", 
     # "26-01-07",
     "26-01-09",
     "26-01-10",
     "26-01-11",
     "26-01-12",
     "26-01-13"
         ]

df = list() 
for date in dates: 
    filename = f"log_{date}.csv"
    filepath = os.path.join('data', filename)
    subprocess.run(["scp", f"root@192.168.1.5:python/victron_system_monitor/{filepath}*", "data/" ])
    _df = pd.read_csv(filepath, index_col=0)
    _df.index = [f'20{date} {x}' for x in _df.index]
    pd.DatetimeIndex(_df.index)
    df.append(_df)
df = pd.concat(df, axis=0)
df.index = pd.DatetimeIndex(df.index)

if "battery_current" not in df.columns:
    df['battery_current'] = np.nan
#%% Battery voltage estimation


R_cabel_mppt = 0.011
R_cable_inverter = 0.0035
voltage_offset = 0
# MPPT voltage measurement
df['battery_voltage_1'] = df.battery_voltage_mppt - (R_cabel_mppt * df.solar_current_mppt) + 0.06
df['battery_voltage_2'] = df.battery_voltage_inverter - (R_cable_inverter * df.inverter_dc_input_current) 
df['est_battery_voltage'] = ((df.battery_voltage_1 + df.battery_voltage_2) / 2) + voltage_offset

nanidx = df.battery_current.isnull()

df.loc[nanidx, 'battery_current'] = df.loc[nanidx, 'battery_power'] / df.loc[nanidx, 'est_battery_voltage'] 



# corretion for hidden constant consumers
const_consumption = 5   # W

#df.solar_current_mppt = df.solar_current_mppt + (const_consumption /  df.battery_voltage_mppt)
df.battery_power -= const_consumption
df.battery_current -= const_consumption / df['est_battery_voltage'] 


#%%
from battery import Battery
from main import get_EKF

Q_tot = 200

# Thevenin model values
R0 = 0.02
R1 = 0.03
C1 = 40000

charge_efficiency = .8
# Thevenin model values
#values for 6.1.26
# R0 = 0.018

# R1 = 0.0003
# C1 = 28000000

# or 

# R0 = 0.05

# R1 = 0.01
# C1 = 50000

R0 = 0.012

R1 = 0.03  
C1 = 10000

# time period
time_step = 60
df = df.resample('1min').mean()
df = df.interpolate(axis=0)
ncells = 8
battery_simulation = Battery(Q_tot, R0, R1, C1, ncells, charge_efficiency)

battery_simulation.actual_capacity =  0.93* battery_simulation.total_capacity
#%%

# measurement noise standard deviation
std_dev = 0.1

#get configured EKF
Kf = get_EKF(R0, R1, C1, Q_tot, std_dev, time_step, battery_simulation)

time         = [0]
true_SoC     = [battery_simulation.state_of_charge]
estim_SoC    = [Kf.x[0,0]]
# true_voltage = [battery_simulation.voltage]
mes_voltage  = [battery_simulation.voltage + np.random.normal(0,0.1,1)[0]]
current      = [battery_simulation.current]
OCV          = [battery_simulation.OCV]
est_OCV      = [battery_simulation.OCV]
def update_step(ds):
    
    measured_voltage = ds.est_battery_voltage
    actual_current = - ds.battery_current
    # actual_current = - ds.battery_power / ds.battery_voltage_inverter
    battery_simulation.current = actual_current
    battery_simulation.update(time_step)

    time.append(time[-1]+time_step)
    current.append(actual_current)
    battery_simulation.voltage
    # true_voltage.append((ds.battery_voltage_inverter + ds.battery_voltage_mppt) / 2)
    
    mes_voltage.append(measured_voltage)
    print(measured_voltage)
    Kf.predict(u=actual_current)
    Kf.update(mes_voltage[-1]  +  R0 * actual_current)
    
    true_SoC.append(battery_simulation.state_of_charge)
    estim_SoC.append(Kf.x[0,0])
    OCV.append(battery_simulation.OCV)
    est_OCV.append(mes_voltage[-1]  +  R0 * actual_current)
    
    if battery_simulation.state_of_charge < .4:
        sdf
    
for t_idx, ds in df.iterrows():
    update_step(ds)
   
df["estimated_SOC"] =  estim_SoC[1:]
df["true_SOC"] =  true_SoC[1:]
df["OCV"] =  OCV[1:]
df["est_OCV"] =  est_OCV[1:]
#plt.plot(true_SoC)
#%%
fig = plt.figure('battery')
plt.clf()
ax1 = plt.subplot(2,2,1)
# Voltage 
df[['battery_voltage_mppt','battery_voltage_inverter', 'battery_voltage_1','battery_voltage_2','OCV', "est_OCV"]].plot(ax=ax1)


ax = plt.subplot(2,2,2, sharex = ax1)
df.solar_power_1.plot(ax=ax, label = 'Solar in')
df.battery_power.plot(ax=ax, label='AC out')
ax.set_title('Fluxes [W]')
plt.legend()
# ax0 = ax.twinx()
ax = plt.subplot(2,2,3)
plot_data =  df.solar_cum_yield.resample('1h').max().diff()
plt.bar(plot_data.index,plot_data,width=.03)

ax =  plt.subplot(2,2,4, sharex = ax1)
df[['estimated_SOC', "true_SOC"]].plot(ax=ax)
plt.grid('on')

cum_output= df.inverter_dc_input_power.resample("1min").mean().cumsum()/60e3
print(f"Total yield over period: { df.solar_cum_yield.iloc[-1] -df.solar_cum_yield.iloc[0]:2.2f} kWh")
print(f"Total output over period: {cum_output.iloc[-1]:2.2f} kWh" )
