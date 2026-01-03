# victron_system_monitor
Python software to be un on Venus OS to log available solar, inverter and battery data and run a simplified battery model

## Requirements
- Root level Venus Os installation (see https://github.com/victronenergy/venus/wiki/raspberrypi-install-venus-image)
- pydbus
- pandas


## Installation
opkg install git
opkg install python3-tomllib

git clone https://github.com/geiges/victron_system_monitor.git
    
### Using uv for package managing
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --system-site-packages --python /usr/bin/python3

## Geting stared

"""

uv run ?`
"""