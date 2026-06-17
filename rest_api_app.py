#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path

from dotenv import load_dotenv
from ecowhen_data_api.app import create_app

from control.api_routes import control_bp

load_dotenv()

app = create_app("api_config.yml")
app.config["CONTROL_DATA_DIR"] = Path("data")
app.register_blueprint(control_bp, url_prefix="/control")

if __name__ == "__main__":
    cfg = app.config["SERVER_CONFIG"]
    app.run(host=cfg.host, port=cfg.port, debug=cfg.debug)
