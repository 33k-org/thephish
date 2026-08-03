#!/usr/bin/env python3
"""
Build-time patch applied to the pinned ThePhish-NG commit (see Dockerfile).
Must run after patches/detailed_verdict_email.py (the Dockerfile enforces
the order) - extends the same report_obs capture and verdict-computation
logic that patch already added.

Our own Ollama analyzer now distinguishes a 4th category - "spam"
(unsolicited bulk/commercial mail, not a security threat) - from "safe"
(genuine, wanted correspondence). Cortex's own taxonomy only has 4 fixed
levels (info/safe/suspicious/malicious - see ollama_analyzer.py's
summary()), so "spam" maps to the "safe" level there for
coloring/aggregation, but the literal raw verdict is captured separately
here so ThePhish-NG's own case-level verdict can still say "Spam"
specifically instead of lumping it in with "Safe".

Two edits to app/services/run_analysis.py:
1. analyze_observables(): also capture the Ollama analyzer's raw
   "verdict" field (not just reasons/confidence).
2. terminate_analysis(): if nothing came back malicious or suspicious,
   check whether the Ollama analyzer's raw verdict was "spam" before
   falling through to "Safe" - and give "Spam" its own resolution status
   (FalsePositive, same as Safe - it's not a real security incident).
"""
import pathlib
import sys

path = pathlib.Path("app/services/run_analysis.py")
src = path.read_text()

old_capture = (
    "\t\t\t\t\tif job['analyzerName'] == 'Ollama_Phishing_Analysis_1_0':\n"
    "\t\t\t\t\t\tollama_full = job.get('report', {}).get('full', {})\n"
    "\t\t\t\t\t\treport_obs['ollama_reasons'] = ollama_full.get('reasons', [])\n"
    "\t\t\t\t\t\treport_obs['ollama_confidence'] = ollama_full.get('confidence')\n"
)
new_capture = (
    "\t\t\t\t\tif job['analyzerName'] == 'Ollama_Phishing_Analysis_1_0':\n"
    "\t\t\t\t\t\tollama_full = job.get('report', {}).get('full', {})\n"
    "\t\t\t\t\t\treport_obs['ollama_reasons'] = ollama_full.get('reasons', [])\n"
    "\t\t\t\t\t\treport_obs['ollama_confidence'] = ollama_full.get('confidence')\n"
    "\t\t\t\t\t\treport_obs['ollama_verdict'] = ollama_full.get('verdict')\n"
)
if old_capture not in src:
    sys.exit("spam_category.py: report_obs capture block not found - upstream may have changed, or detailed_verdict_email.py didn't run first")
src = src.replace(old_capture, new_capture, 1)

old_classify = (
    "\tif malicious_observables > 0:\n"
    "\t\tverdict = \"Malicious\"\n"
    "\t# If there is at least one suspicious observable, then the email is suspicious\n"
    "\telif suspicious_observables > 0:\n"
    "\t\tverdict = \"Suspicious\"\n"
    "\t# Else the email is safe\n"
    "\telse:\n"
    "\t\tverdict = \"Safe\"\n"
)
new_classify = (
    "\tif malicious_observables > 0:\n"
    "\t\tverdict = \"Malicious\"\n"
    "\t# If there is at least one suspicious observable, then the email is suspicious\n"
    "\telif suspicious_observables > 0:\n"
    "\t\tverdict = \"Suspicious\"\n"
    "\t# Our own Ollama analyzer distinguishes spam (unsolicited bulk/\n"
    "\t# commercial mail) from safe (genuine, wanted correspondence) -\n"
    "\t# neither is malicious/suspicious, but they're not the same thing.\n"
    "\telif any(r.get('ollama_verdict') == 'spam' for r in reports_observables):\n"
    "\t\tverdict = \"Spam\"\n"
    "\t# Else the email is safe\n"
    "\telse:\n"
    "\t\tverdict = \"Safe\"\n"
)
if old_classify not in src:
    sys.exit("spam_category.py: verdict classification block not found - upstream may have changed")
src = src.replace(old_classify, new_classify, 1)

old_resolution = (
    "\t\telif verdict == 'Suspicious':\n"
    "\t\t\tresolution_status = 'Indeterminate'\n"
)
new_resolution = (
    "\t\telif verdict == 'Suspicious':\n"
    "\t\t\tresolution_status = 'Indeterminate'\n"
    "\n"
    "\t\telif verdict == 'Spam':\n"
    "\t\t\tresolution_status = 'FalsePositive'\n"
)
if old_resolution not in src:
    sys.exit("spam_category.py: resolution_status branch not found - upstream may have changed")
src = src.replace(old_resolution, new_resolution, 1)

path.write_text(src)
