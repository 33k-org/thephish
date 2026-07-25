#!/usr/bin/env python3
"""
Build-time patch applied to the pinned ThePhish-NG commit (see Dockerfile).

Upstream's verdict-email body is a single bare sentence: "Thanks for your
submission. The e-mail with subject [X] you submitted has been classified
as Y." No reasoning, no indication of what was actually flagged. This
patch pulls in our own Ollama analyzer's reasoning/confidence (already
computed, just discarded before this patch) and a list of flagged
observables, building a more useful reply body.

Two edits to app/services/run_analysis.py:
1. analyze_observables(): capture Ollama_Phishing_Analysis_1_0's
   `reasons`/`confidence` report fields (see ollama-analyzer/Ollama/
   ollama_analyzer.py's self.report() call for the schema) onto the
   report_obs dict alongside the level it already captures.
2. terminate_analysis(): build the richer description from those captured
   fields instead of the bare one-liner.
"""
import pathlib
import sys

path = pathlib.Path("app/services/run_analysis.py")
src = path.read_text()

old_capture = "\t\t\t\t\treport_obs['analyzer_result'] = level\n"
new_capture = old_capture + (
    "\n"
    "\t\t\t\t\t# Capture extra detail from our own Ollama analyzer for a\n"
    "\t\t\t\t\t# richer verdict-email body - see terminate_analysis().\n"
    "\t\t\t\t\tif job['analyzerName'] == 'Ollama_Phishing_Analysis_1_0':\n"
    "\t\t\t\t\t\tollama_full = job.get('report', {}).get('full', {})\n"
    "\t\t\t\t\t\treport_obs['ollama_reasons'] = ollama_full.get('reasons', [])\n"
    "\t\t\t\t\t\treport_obs['ollama_confidence'] = ollama_full.get('confidence')\n"
)
if old_capture not in src:
    sys.exit("detailed_verdict_email.py: report_obs capture line not found - upstream may have changed")
src = src.replace(old_capture, new_capture, 1)

old_description = (
    "\t\t# Add a description to the third task that is understood by the Mailer responder\n"
    "\t\t# The description must start with \"mailto:<email>\" and then continue with the body of the email to send to the user\n"
    "\t\ttask_update = {\n"
    "\t\t\t\"description\": \"mailto:\" + mail_to + \"\\nThanks for your submission. The e-mail with subject [{0}] you submitted has been classified as {1}\".format(\n"
    "\t\t\t\tcase[\"title\"][11:], verdict)\n"
    "\t\t}\n"
)
new_description = (
    "\t\t# Build a more detailed reply body than a bare one-line verdict -\n"
    "\t\t# pull out our own Ollama analyzer's reasoning/confidence (captured\n"
    "\t\t# in analyze_observables() above) and a list of flagged items.\n"
    "\t\tdetail_lines = []\n"
    "\t\tfor report_obs in reports_observables:\n"
    "\t\t\tif report_obs.get('analyzer_name') == 'Ollama_Phishing_Analysis_1_0' and report_obs.get('ollama_reasons'):\n"
    "\t\t\t\tconfidence = report_obs.get('ollama_confidence')\n"
    "\t\t\t\theader = \"Automated analysis findings\"\n"
    "\t\t\t\tif confidence is not None:\n"
    "\t\t\t\t\theader += \" (confidence: {0}%)\".format(confidence)\n"
    "\t\t\t\tdetail_lines.append(header + \":\")\n"
    "\t\t\t\tfor reason in report_obs['ollama_reasons']:\n"
    "\t\t\t\t\tdetail_lines.append(\"- \" + str(reason))\n"
    "\t\t\t\tbreak\n"
    "\n"
    "\t\tflagged_lines = []\n"
    "\t\tfor report_obs in reports_observables:\n"
    "\t\t\tif report_obs.get('analyzer_result') in ('malicious', 'suspicious'):\n"
    "\t\t\t\tflagged_lines.append(\"- {0}: {1} ({2})\".format(\n"
    "\t\t\t\t\treport_obs['observable_type'], report_obs['observable_name'], report_obs['analyzer_result']))\n"
    "\n"
    "\t\tdescription_body = \"Thanks for your submission.\\n\\nThe e-mail with subject [{0}] you submitted has been classified as {1}.\".format(\n"
    "\t\t\tcase[\"title\"][11:], verdict)\n"
    "\t\tif detail_lines:\n"
    "\t\t\tdescription_body += \"\\n\\n\" + \"\\n\".join(detail_lines)\n"
    "\t\tif flagged_lines:\n"
    "\t\t\tdescription_body += \"\\n\\nFlagged items:\\n\" + \"\\n\".join(flagged_lines)\n"
    "\n"
    "\t\t# Add a description to the third task that is understood by the Mailer responder\n"
    "\t\t# The description must start with \"mailto:<email>\" and then continue with the body of the email to send to the user\n"
    "\t\ttask_update = {\n"
    "\t\t\t\"description\": \"mailto:\" + mail_to + \"\\n\" + description_body\n"
    "\t\t}\n"
)
if old_description not in src:
    sys.exit("detailed_verdict_email.py: description task_update block not found - upstream may have changed")
src = src.replace(old_description, new_description, 1)

path.write_text(src)
