#!/usr/bin/env python3
"""
Build-time patch applied to the pinned ThePhish-NG commit (see Dockerfile).
Must run AFTER patches/notify_wrong_format.py (the Dockerfile enforces the
order) - this wires app/utils/inline_forward.py (copied in separately, see
Dockerfile) into both places that need it, so an inline-forwarded email
that has no .eml attachment gets a synthesized one instead of falling
through to the wrong-format notice.

- app/services/list_emails.py: right before the existing
  `if (eml_attachment_found == True):` check, try synthesis first and set
  eml_attachment_found/attached_mail_subject if it succeeds - the
  existing (already-patched) if/else below this needs no further changes.
- app/services/case_from_email.py: obtain_eml() falls back to the same
  synthesis when no attachment part was found, right before it returns.
"""
import pathlib
import sys

# --- list_emails.py ---
path = pathlib.Path("app/services/list_emails.py")
src = path.read_text()

old_import_anchor = "from app.utils import config as config_utils\n"
new_import_anchor = old_import_anchor + "from app.utils import inline_forward\n"
if old_import_anchor not in src:
    sys.exit("enable_inline_forward.py: list_emails.py import anchor not found - upstream may have changed, or notify_wrong_format.py didn't run first")
src = src.replace(old_import_anchor, new_import_anchor, 1)

old_if = "\t\tif (eml_attachment_found == True):\n"
new_if = (
    "\t\tif not eml_attachment_found:\n"
    "\t\t\t# No EML attachment - try to recover one from an inline\n"
    "\t\t\t# forward (quoted text in the body) before giving up.\n"
    "\t\t\tsynthesized = inline_forward.extract(msg, body)\n"
    "\t\t\tif synthesized is not None:\n"
    "\t\t\t\teml_attachment_found = True\n"
    "\t\t\t\tattached_mail_subject = synthesized.get('Subject', '(no subject)')\n"
    "\n"
    "\t\tif (eml_attachment_found == True):\n"
)
if old_if not in src:
    sys.exit("enable_inline_forward.py: list_emails.py eml_attachment_found check not found - upstream may have changed")
src = src.replace(old_if, new_if, 1)

path.write_text(src)

# --- case_from_email.py ---
path = pathlib.Path("app/services/case_from_email.py")
src = path.read_text()

old_import_anchor = "from app.utils import imap_pool, whitelist\n"
new_import_anchor = old_import_anchor + "from app.utils import inline_forward\n"
if old_import_anchor not in src:
    sys.exit("enable_inline_forward.py: case_from_email.py import anchor not found - upstream may have changed")
src = src.replace(old_import_anchor, new_import_anchor, 1)

old_return = "\t\treturn internal_msg, external_from_field\n"
new_return = (
    "\t\tif internal_msg is None:\n"
    "\t\t\t# No EML attachment found - try to recover one from an inline\n"
    "\t\t\t# forward, same as app/services/list_emails.py.\n"
    "\t\t\tinternal_msg = inline_forward.extract(msg)\n"
    "\n"
    "\t\treturn internal_msg, external_from_field\n"
)
if old_return not in src:
    sys.exit("enable_inline_forward.py: case_from_email.py obtain_eml return not found - upstream may have changed")
src = src.replace(old_return, new_return, 1)

path.write_text(src)
