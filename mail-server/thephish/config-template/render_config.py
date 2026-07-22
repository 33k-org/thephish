#!/usr/bin/env python3
"""Renders ThePhish-NG's config/ directory from templates + environment.

configuration.json is the only file with secrets (IMAP/TheHive/Cortex
credentials) - substituted from the environment via os.path.expandvars.
The rest (whitelist, analyzer levels, logging) have no secrets and are
copied verbatim.
"""
import os
import shutil
from pathlib import Path

TEMPLATE_DIR = Path("/opt/thephish-config-template")
CONFIG_DIR = Path("/opt/thephish/config")

CONFIG_DIR.mkdir(parents=True, exist_ok=True)

template = (TEMPLATE_DIR / "configuration.json").read_text()
rendered = os.path.expandvars(template)
(CONFIG_DIR / "configuration.json").write_text(rendered)

for name in ("whitelist.json", "analyzers_level_conf.json", "logging_conf.json"):
    shutil.copyfile(TEMPLATE_DIR / name, CONFIG_DIR / name)
