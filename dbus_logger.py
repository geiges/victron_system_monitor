#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan  2 17:53:44 2026

@author: and
"""
import os
import time
import shutil
import pathlib
import csv
import pytz
import json
import yaml
from csv import DictWriter, DictReader
from pydbus import SystemBus
from utils import File_Logger, str2datetime, datetime2str
from datetime import datetime, timedelta

import config_default as config
import power_system

timezone = pytz.timezone(config.tz)

simulate_system = config.simulate_system

class Logger_Daily_aggregates():
    
    def __init__(self, config):
        
        self.cfg = config
        
        self.cfg = dict(
            fieldnames = ['date', 'solar_yield'],
            output_dir = 'data/daily/',
            input_dir  = 'data')
        
        self.cfg["out_filepath"] = os.path.join(
            self.cfg["output_dir"], 'solar_daily.csv')
        
        if not os.path.exists(self.cfg["out_filepath"]):
            self._init_output_file()
            
        self.last_date_str = self._get_last_date_logged()
        print(self.last_date_str)
        
        os.makedirs(self.cfg['output_dir'],exist_ok=True)
        
        
        
    def _get_last_date_logged(self):
        
        if not os.path.exists(self.cfg["out_filepath"]):
            return "NaT"
        
        with open(self.cfg["out_filepath"], mode="r") as fid:
            	data = fid.readlines() 
        lastRow = data[-1]
        
        
        last_date_str =  lastRow.split(',')[0]
        return last_date_str
    
    def _compute_day_yield(self, file):
        path = pathlib.Path(file)
        date_str = path.name.replace('log_','').replace('.csv','')
        filepath = os.path.join(self.cfg['input_dir'], file)
        assert os.path.exists(filepath)
        with open(filepath, mode="r") as fid:
            reader = DictReader(fid)
            first = next(reader)
            
            for row in reader:
                pass
            print(row)
            last = row
            
            data = dict(
                date = date_str,
                solar_yield = round(
                    float(last['mppt150/total_yield']) - float(first['mppt150/total_yield']),
                    config.round_digits
                    )
                )
            print(f"{first['mppt150/power_yield']} - {last['mppt150/power_yield']} = {data['solar_yield']}")
        return data
        
    
    def _init_output_file(self):
        files = sorted(x for x in os.listdir(self.cfg["input_dir"]) 
                       if (x.startswith('log') and (x.endswith('.csv')))
                       )
        
        with open(self.cfg["out_filepath"], mode="w") as fid_out:
            writer = DictWriter(fid_out, self.cfg["fieldnames"])
            writer.writeheader()
            for file in files:
                data = self._compute_day_yield(file)
                writer.writerow(data)
                
                
        
    def update_daily_aggregates(self, date_str):
        
        if self.last_date_str != date_str:
            
            time_delta = str2datetime(date_str) - str2datetime(self.last_date_str)
            base = str2datetime(self.last_date_str)
            date_list = [base + timedelta(days=x) for x in range(1, time_delta.days)]
            print(date_list)
            
            with open(self.cfg["out_filepath"], mode="a") as fid_out:
                writer = DictWriter(fid_out, self.cfg["fieldnames"])
                for date in date_list:
                    filepath  = "log_{date_str}.csv".format(date_str=datetime2str(date))
                    data = self._compute_day_yield(filepath)
                    writer.writerow(data)
                
            
            self.last_date_str = date_str
            print("finished aggregate update")
        

def update_existing_file(filename: str,
                         fieldnames: list[str],) -> str:

    now = datetime.now(tz=timezone) # current date and time

    date_str = now.strftime(config.date_format)

    # date_str = pd.Timestamp.now().strftime(config.date_format)

    if not os.path.exists(filename):
        return 'NaT'

    tt = time.time()
    print("Loading from disk and extending with new columns..", end="")
    # df = pd.read_csv(filename, index_col=0)
    reader = csv.DictReader(open(filename))
    columns = reader.fieldnames
    # update file if new columns or new order

    # header is only updated if more fieldnames are not all in existing columns
    update_header = not set(fieldnames).issubset(set(columns))

    if update_header:
        #
        shutil.move(filename, filename + '_previous_data')
        reader = csv.DictReader(open(filename + '_previous_data'))
        with open(filename, mode="a") as f:
            writer = DictWriter(f, fieldnames)
            writer.writeheader()
            for row in reader:
                writer.writerow(row)


    print(f".done in {time.time() - tt:2.2f}s")

    return date_str

def retrieve_data(bus, variables_to_log, debug):

    data = dict()
    for var_name, var_conf in variables_to_log.items():

        if debug:
            print(f'Getting {var_conf["address"]} from { var_conf["dbus_device"]}')
        var_value = bus.get(
            var_conf["dbus_device"],
            var_conf["address"]
            ).GetValue()

        try:
            if var_name not in config.non_numeric_var:
                var_value = round(var_value,config.round_digits)
            data[var_name] = var_value
        except Exception:
            print(f'Failed to read  {var_conf["address"]} from { var_conf["dbus_device"]}')
    return data



def _toggle_command_id(short_name: str, basename: str, suffix: str) -> str:
    return f"{short_name}_{basename}_{suffix}"


def save_system_configuration(psystem, bus,
                               sys_config_path: str = 'data/system_configuration.yaml',
                               api_config_path: str = 'api_config.yml'):
    """
    Write data/system_configuration.yaml with actual runtime D-Bus service names
    and toggle command info, then regenerate the command_endpoints in api_config.yml.
    Called once at startup after bus discovery.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    components = {}

    for short_name, component in psystem.items():
        service = component.get_interface(bus)
        toggle_commands = []

        for state in component.component_states:
            if not state.toggle_values:
                continue
            toggle_commands.append({
                'basename': state.basename,
                'path': state.subaddress,
                'values': list(state.toggle_values),
                'read_command_id':   _toggle_command_id(short_name, state.basename, 'read'),
                'toggle_command_id': _toggle_command_id(short_name, state.basename, 'toggle'),
            })

        components[short_name] = {
            'product_name': component.product_name,
            'service': service,
            'available': service is not None,
            'toggle_commands': toggle_commands,
        }

    with open(sys_config_path, 'w') as f:
        yaml.dump(
            {'generated_at': now, 'components': components},
            f, default_flow_style=False, allow_unicode=True, sort_keys=False,
        )

    _regenerate_api_config_commands(components, api_config_path)


def _regenerate_api_config_commands(components: dict, api_config_path: str = 'api_config.yml'):
    """
    Replace only the command_endpoints section of api_config.yml with entries
    derived from the discovered D-Bus services. All other sections are preserved.
    """
    with open(api_config_path) as f:
        config = yaml.safe_load(f)

    cmd_eps = []
    for short_name, comp in components.items():
        service = comp.get('service')
        if not service or not comp.get('available'):
            continue
        for tc in comp.get('toggle_commands', []):
            cmd_eps.append({
                'id': tc['read_command_id'],
                'type': 'dbus_read',
                'description': f"Read {short_name} {tc['basename']}",
                'service': service,
                'path': tc['path'],
            })
            cmd_eps.append({
                'id': tc['toggle_command_id'],
                'type': 'dbus_toggle',
                'description': f"Toggle {short_name} {tc['basename']}",
                'service': service,
                'path': tc['path'],
                'values': tc['values'],
            })

    config['command_endpoints'] = cmd_eps

    with open(api_config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def retrieve_states(bus, states_to_log, debug=False):
    """Read current discrete state values from D-Bus."""
    values = {}
    for var_name, conf in states_to_log.items():
        try:
            if debug:
                print(f'Getting state {conf["address"]} from {conf["dbus_device"]}')
            values[var_name] = bus.get(conf['dbus_device'], conf['address']).GetValue()
        except Exception:
            values[var_name] = None
    return values


def encode_state_code(state_values, ordered_names):
    """
    Encode all states into a zero-padded string. Each character position
    corresponds to one state variable. The digit is the raw D-Bus integer
    value (9 = unknown/out-of-range).
    """
    digits = []
    for name in ordered_names:
        raw = state_values.get(name)
        if raw is None or not (0 <= raw <= 8):
            digits.append('9')
        else:
            digits.append(str(raw))
    return ''.join(digits)


def save_state_mapping_yaml(states_to_log, path='data/state_mapping.yaml'):
    """
    Write a YAML file documenting the state column encoding.
    Each position in the 'state' string maps to one state variable.
    Called once at startup.
    """
    state_list = [
        {
            'position': pos,
            'name': name,
            'encoding': {str(k): v for k, v in conf['mapping'].items()},
        }
        for pos, (name, conf) in enumerate(states_to_log.items())
    ]
    with open(path, 'w') as f:
        yaml.dump({'states': state_list}, f, default_flow_style=False, allow_unicode=True)


def update_loop(debug=False):
    
    if os.environ.get("VICTRON_TEST_SESSION_BUS"):
        from pydbus import SessionBus
        bus = SessionBus()
    else:
        bus = SystemBus()

    psystem = power_system.init_power_system(system_components = config.system_components,
                                             measurement_components=config.measurement_components
                                             )

    variables_to_log, missing_components = psystem.get_variables_to_log(bus)
    
    states_to_log, missing_components = psystem.get_states_to_log(bus)
    ordered_state_names = list(states_to_log.keys())
    save_state_mapping_yaml(states_to_log)
    save_system_configuration(psystem, bus)

    "variables that are summed up over all components to system value"
    state_variables_to_sum = [
        "power_yield",
        "total_yield"
        ]



    t_now = datetime.now(tz=timezone)
    
    meas_logger = File_Logger("data/log_{date_str}.csv",
                                    config)
    sim_logger = File_Logger("data/sim_{date_str}.csv",
                                    config)
    
    state = dict()
    
    now = datetime.now(tz=timezone) # current date and time

    state['running_since'] = now.strftime("%y-%m-%d %H:%M")

    
    daily_logger =Logger_Daily_aggregates(config)
    
    
    if simulate_system:
        import simulation

        simulator = simulation.System_Simulation(config.batt_config_V1)
        
        curr_output_file = sim_logger.get_output_file_path(t_now)
        if os.path.exists(curr_output_file):
            with open(curr_output_file, 'r') as fid:
                reader = csv.DictReader(fid)
                
                for row in reader:
                    print(row)
                    soc = row['SOC_counted']
                    t_previous = row['time']
                    
        
        
            t_prev = datetime.strptime(t_previous, config.time_format)
            
            t_previous = datetime(year = t_now.year, month = t_now.month, day = t_now.day,
                                  hour = t_prev.hour, minute = t_prev.minute, second=t_prev.second)
            
            localtz = pytz.timezone(config.tz)
            t_previous = localtz.localize(t_previous)
    
            simulator.set_state(float(soc), t_previous )
            simulator.initilized = True

    else:
        simulator = None

    while True:

        t_now = datetime.now(tz=timezone) # current date and time
        date_str =  t_now.strftime(config.date_format)

        try:
            data = retrieve_data(bus, variables_to_log, debug)
            state_values = retrieve_states(bus, states_to_log, debug)
            data['state'] = encode_state_code(state_values, ordered_state_names)
        except Exception as E:
            data = None
            if debug:
                print(f"Exception {E} was raised.")
                print("Skipping this update loop")

        if data is not None:
            date_str =  t_now.strftime(config.date_format)
            daily_logger.update_daily_aggregates(date_str)
            
            row_data = meas_logger.log_step(t_now, data)
            
            if row_data is not None:
                   
                #adding logger row data to state
                state.update(row_data)
                
                if simulate_system:
                    sim_row = simulator.update(raw_data=row_data,
                                               t_now = t_now,
                                               psystem=psystem)
                    
                    #adding simulation row data to state
                    state.update(sim_row)
                    
                    state['time_to_low_battery'] = simulator.time_to_low_battery()
                    
                    
                        
                    for key, var_value in sim_row.items():
                        
                        if key == 'time':
                            continue
                        sim_row[key] = round(var_value, config.round_digits)
                    
                    sim_logger.log_step(t_now, sim_row)
        
        
        
        
                # completing state information with system sum varibles
                for sum_var in state_variables_to_sum:
                    
                    #find all non-system variables ending with sum_var
                    vars_to_sum = [x for x in row_data.keys() if (not x.startswith('system')) and x.endswith(sum_var)]
                    sum_value = sum(row_data[x] for x in vars_to_sum)
                    state[f'system/{sum_var}'] = sum_value
                
                with open('data/state.json', 'w') as fp:
                    json.dump(state, fp)
        t_calc =  datetime.now(tz=timezone) - t_now
        
        print(f"Timestep done in {(datetime.now(tz=timezone) - t_now).total_seconds():2.2f}s")
       
        time.sleep(max(0, config.log_interval - t_calc.total_seconds()))
        

def main(debug=False):
    os.makedirs("data", exist_ok=True)
    update_loop(debug=debug)


if __name__ == '__main__':
    main(debug=False)
    # daily_logger =Logger_Daily_aggregates(config)

    # now = datetime.now(tz=timezone) # current date and time
    # date_str = now.strftime(config.date_format)

    # daily_logger.update_daily_aggregates(date_str)
