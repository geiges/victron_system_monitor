#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 13 09:52:12 2026

@author: and
"""

class Power_system(dict):
    """
    System class to facilitate simple component access
    """
    
    def __init__(self, components):
        """
        Setting up the system from a list of individual components. The property
        short_name is used as dict-like keys to manage the components access.

        Parameters
        ----------
        components : list of components (see components.py)
           

        Returns
        -------
        None.

        """
        for component in components:
            
            self[component.short_name] = component
            
            
def init_power_system(system_components,
                      measurement_components):
    """
    Return the power system instance including all initialised components and 
    available measurements components.
    """
    
    power_system = Power_system(system_components)

    for component, measurement_setup in measurement_components.items():
        power_system[component].init_measurement_correction(**measurement_setup)
    
    return power_system