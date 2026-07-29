#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jul 29 10:44:13 2026

@author: and
"""
import os
import config_default as config
import power_system


if __name__ == "__main__":
    
    if os.environ.get("VICTRON_TEST_SESSION_BUS"):
        from pydbus import SessionBus
        bus = SessionBus()
    else:
        from pydbus import SystemBus
        bus = SystemBus()

    psystem = power_system.init_power_system(system_components = config.system_components,
                                             measurement_components=config.measurement_components
                                             )

    variables_to_log, missing_components = psystem.get_variables_to_log(bus)
    
    print(f'variables to log: {variables_to_log}')
    print(f'Missing compontents: {missing_components}')
    
    states_to_log, missing_components = psystem.get_states_to_log(bus)
    
    print(f'states to log: {states_to_log}')
    print(f'Missing compontents: {missing_components}')
    