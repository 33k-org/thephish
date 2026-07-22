#!/bin/sh
set -eu

python3 /opt/thephish-config-template/render_config.py

exec python3 run.py
