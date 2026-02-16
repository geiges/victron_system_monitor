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
from battery import Battery
from kalman import ExtendedKalmanFilter

# sys.path.append('/home/and/python/Battery-Kalman/Python/')
#%%
dates = [
     "26-01-13",
     "26-01-14",
     "26-01-15",
     "26-01-16",
     "26-01-17",
     "26-01-18",
     "26-01-19",
     # "26-01-20",
     # "26-01-21",
     # "26-01-22",
     # "26-01-23",
     # "26-01-24",
     # "26-01-25",
     # "26-01-26",
     # "26-01-27",
     # "26-01-28",
     # "26-01-29",
     # "26-01-30",
     # "26-01-31",
     # "26-02-01",
     # "26-02-02",
     # "26-02-03",    
     # "26-02-04",
     # "26-02-05",
     # "26-02-06",
     # "26-02-07",
     # "26-02-08",
     # "26-02-09",    
     # "26-02-10",
     
     # "26-02-11",    
     # "26-02-12",
         
     # "26-02-13",    
     # "26-02-14",  
     # "26-02-15",
     # "26-02-16",
         ]

df = list()
subprocess.run(["rsync", "-av", "root@192.168.1.5:/data/python/victron_system_monitor/data", "." ])
# subprocess.run(['sh', "rsync.sh"])
for date in dates: 
    filename = f"log_{date}.csv"
    filepath = os.path.join('data', filename)
    
    now = pd.Timestamp.now()
    date_file = pd.Timestamp('20' + date)
    
    # subprocess.run(["scp", f"root@192.168.1.5:/data/python/victron_system_monitor/{filepath}*", "data/" ])
    _df = pd.read_csv(filepath, index_col=0)
    
    
    
    idx_to_drop = _df.index[_df.index.str.contains('time')]
    _df = _df.drop(idx_to_drop)
    _df.index = [f'20{date} {x}' for x in _df.index]
    
    _df= _df.astype(float)
    # pd.DatetimeIndex(_df.index)
    df.append(_df)
df = pd.concat(df, axis=0)
df.index = pd.DatetimeIndex(df.index)

if "battery_current" not in df.columns:
    df['battery_current'] = np.nan
#%% Battery voltage estimation


R_cabel_mppt = 0.011
R_cable_inverter = 0.0035
voltage_offset = -.1
# MPPT voltage measurement
df['battery_voltage_1'] = df.battery_voltage_mppt - (R_cabel_mppt * df.solar_current_mppt) 
df['battery_voltage_2'] = df.battery_voltage_inverter - (R_cable_inverter * df.inverter_dc_input_current) +- 0.06
df['est_battery_voltage'] = ((df.battery_voltage_1 + df.battery_voltage_2) / 2) + voltage_offset
na_idx = df.index[df.est_battery_voltage.isnull()]
df.loc[na_idx,'est_battery_voltage']  = df.loc[na_idx,'battery_voltage_1']

nanidx = df.battery_current.isnull()

df.loc[nanidx, 'battery_current'] = df.loc[nanidx, 'battery_power'] / df.loc[nanidx, 'est_battery_voltage'] 



# corretion for hidden constant consumers
const_consumption = 8   # W

#df.solar_current_mppt = df.solar_current_mppt + (const_consumption /  df.battery_voltage_mppt)
df.battery_power -= const_consumption
df.battery_current -= const_consumption / df['est_battery_voltage'] 

df['battery_out'] = df.battery_power- df.solar_power_1

#%%

battery_capacity = 210

# Thevenin model values
R0 = 0.02
R1 = 0.03
C1 = 40000

charge_efficiency = 1.0
# Thevenin model values
#values for 6.1.26
# R0 = 0.018

# R1 = 0.0003
# C1 = 28000000

# or 

# R0 = 0.05

# R1 = 0.01
# C1 = 50000

R0 = 0.01

R1 = 0.04
C1 = 2000

# time period
time_step = 60
df = df.resample('1min').mean()
df = df.interpolate(axis=0)
ncells = 8
battery_simulation = Battery(battery_capacity, R0, R1, C1, ncells, charge_efficiency)

battery_simulation.actual_capacity =  0.6* battery_simulation.total_capacity
#battery_simulation.plot_SOCV_relation()
# sdf
#%%

# measurement noise standard deviation
std_dev = 2.

#get configured EKF
Kf = ExtendedKalmanFilter(std_dev, battery_simulation)
Kf.set_state(SOC=0.65, 
             RC_voltage = 0.0)
time         = [0]
true_SoC     = [battery_simulation.state_of_charge]
estim_SoC    = [Kf.x[0,0]]
# true_voltage = [battery_simulation.voltage]
mes_voltage  = [battery_simulation.voltage]
current      = [battery_simulation.current]
OCV          = [battery_simulation.OCV]
est_OCV      = [battery_simulation.OCV]
   
def update_step(ds):
    
    measured_voltage = ds.est_battery_voltage
    actual_current = - ds.battery_current
    # actual_current = - ds.battery_power / ds.battery_voltage_inverter
    # battery_simulation.current    = actual_current
    battery_simulation.update(time_step, actual_current)

    time.append(time[-1]+time_step)
    current.append(actual_current)
    battery_simulation.voltage
    # true_voltage.append((ds.battery_voltage_inverter + ds.battery_voltage_mppt) / 2)
    
    mes_voltage.append(measured_voltage)
    print(measured_voltage)
    Kf.predict(time_delta=time_step, 
               u=actual_current)
    Kf.update(mes_voltage[-1] -  R0 * actual_current, u=actual_current)
    Kf.x[0,0]
    
    if (Kf.x[0,0] < 1.0) or  (abs(actual_current)> 5.):
        true_SoC.append(battery_simulation.state_of_charge)
        estim_SoC.append(Kf.x[0,0])
    else:
        battery_simulation.set_state_of_charge(SOC=1.0)
        true_SoC.append(battery_simulation.state_of_charge)
        estim_SoC.append(Kf.x[0,0])

    OCV.append(battery_simulation.OCV)
    est_OCV.append(mes_voltage[-1]  +  R0 * actual_current)
    

        
    # est_OCV.append(Kf.y_pred +  R0 * actual_current)
    # if battery_simulation.state_of_charge < .4:
        
    
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
ax1 = plt.subplot(3,1,1)
# Voltage 
df[['battery_voltage_mppt','battery_voltage_inverter', 'battery_voltage_1','battery_voltage_2','OCV', "est_OCV"]].plot(ax=ax1)
plt.grid('on')

ax = plt.subplot(3,1,2, sharex = ax1)
df.solar_power_1.plot(ax=ax, label = 'Solar DC in')
plt.fill_between(x = df.index,y1=0,y2=df.solar_power_1, color='royalblue',alpha=.1)
# plt.yscale('log')
plt.grid('on')
ax_twin = plt.twinx(ax)
color = 'red'
# df.battery_power.plot(ax=ax_twin,color='orange', label='AC out')
df.battery_out.plot(ax=ax_twin,color=color, label='DC out')
plt.fill_between(x = df.index,y1=0,y2=df.battery_out, color=color,alpha=.1)
ax_twin.tick_params(axis='y', labelcolor=color)

ax.set_title('Fluxes [W]')

plt.legend()    


ax =  plt.subplot(3,1,3, sharex = ax1)
df[['estimated_SOC', "true_SOC"]].plot(ax=ax)
plt.grid('on')
ax_twin = plt.twinx(ax)
color = 'gray'
# df.battery_power.plot(ax=ax_twin,color='orange', label='AC out')
df.battery_temperature.plot(ax=ax_twin,color=color, label='Battery temperature')


inverter_output_idx = df.inverter_ac_output>0

cum_dc_output= (df.battery_power[inverter_output_idx] -  df.solar_power_1[inverter_output_idx]).resample("1min").mean().cumsum()/60e3
cum_ac_output = df.inverter_ac_output.resample("1min").mean().cumsum()/60e3



print(f"Total yield over period: { df.solar_cum_yield.iloc[-1] -df.solar_cum_yield.iloc[0]:2.2f} kWh")
print(f"Total DC battery output over period: {cum_dc_output.iloc[-1]:2.2f} kWh" )
print(f"Total AC inverter output over period: {cum_ac_output.iloc[-1]:2.2f} kWh" )

cum_yielt_today = df.solar_cum_yield.resample('1d').max().diff()
output_today = cum_ac_output.resample('1d').max().diff()
print(f"Total AC inverter output today: {output_today.iloc[-1]:2.2f} kWh" )
print(f"Total solar harvest today: {cum_yielt_today.iloc[-1]:2.2f} kWh" )

plt.tight_layout()
    