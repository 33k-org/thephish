#!/usr/bin/env python3
"""
Build-time patch applied to the pinned ThePhish-NG commit (see Dockerfile).

Upstream only auto-resolves the case and auto-sends the verdict email via
Cortex's Mailer responder for "Malicious"/"Safe" verdicts - "Suspicious"
is deliberately left open for a human to write and send the reply by hand
(app/services/run_analysis.py's `if verdict != "Suspicious":` gate).

Requested behavior for this deployment: the whole pipeline should run
unattended end-to-end regardless of verdict, always replying to whoever
forwarded the email. This patch makes "Suspicious" take the same
auto-resolve+notify path as "Malicious"/"Safe", closing the case with
TheHive's "Indeterminate" resolution status (MISP export stays
Malicious-only - unchanged).
"""
import pathlib
import sys

path = pathlib.Path("app/services/run_analysis.py")
src = path.read_text()

old_gate = '\tif verdict != "Suspicious":\n'
new_gate = "\tif True:  # always resolve + notify sender, regardless of verdict\n"
if old_gate not in src:
    sys.exit("auto_resolve_all_verdicts.py: verdict gate not found - upstream may have changed, patch needs updating")
src = src.replace(old_gate, new_gate, 1)

old_resolution = "\t\telif verdict == 'Safe':\n\t\t\tresolution_status = 'FalsePositive'\n"
new_resolution = (
    "\t\telif verdict == 'Safe':\n\t\t\tresolution_status = 'FalsePositive'\n"
    "\n"
    "\t\telif verdict == 'Suspicious':\n\t\t\tresolution_status = 'Indeterminate'\n"
)
if old_resolution not in src:
    sys.exit("auto_resolve_all_verdicts.py: Safe-verdict resolution_status block not found - upstream may have changed, patch needs updating")
src = src.replace(old_resolution, new_resolution, 1)

path.write_text(src)
