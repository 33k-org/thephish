#!/usr/bin/env python3
"""
Build-time patch applied to the pinned ThePhish-NG commit (see Dockerfile).

Pre-existing bug, unrelated to any of our other patches - confirmed live:
two real forwarded emails (both entirely ordinary marketing/newsletter
mail, not deliberately malformed) crashed /api/analysis outright with
UnicodeEncodeError: 'ascii' codec can't encode character '\\u2007'/'\\u2019'
in position N. app/services/case_from_email.py's parse_eml() serializes
the parsed message back to bytes (to compute its hash and attach it as a
"file" observable) via `email.generator.BytesGenerator(inmem_file)`.

First attempt at a fix (passing `policy=email.policy.SMTPUTF8`) turned out
not to work: confirmed by reading CPython's own email/generator.py source
that BytesGenerator.write() is hardcoded to
`self._fp.write(s.encode('ascii', 'surrogateescape'))` regardless of what
policy is configured - the policy only affects other decisions (like
_handle_text's surrogate-vs-real-unicode check), not the actual byte
encoding. So any part whose payload is a genuine Python str containing a
real (non-surrogate-escaped) Unicode character - extremely common in real
HTML email: smart quotes, figure spaces, em-dashes - fails no matter what
policy is passed, because there's no code path in BytesGenerator that
ever encodes as anything but ASCII.

Real fix: use the plain string `Generator` instead (whose `write()` has no
such restriction), flatten to a StringIO, then UTF-8-encode the result
ourselves into the BytesIO `parse_eml()` already builds `eml_file_tuple`
from. Confirmed working against both of the real characters that crashed
production traffic.

Since case_from_email.main() calls parse_eml() before creating the case,
the original bug meant total silence to the sender - no case, no
notification, nothing, for completely ordinary real-world forwarded
email, not just edge cases.
"""
import pathlib
import sys

path = pathlib.Path("app/services/case_from_email.py")
src = path.read_text()

old_gen = (
    "\tinmem_file = io.BytesIO()\n"
    "\tgen = email.generator.BytesGenerator(inmem_file)\n"
    "\tgen.flatten(internal_msg)\n"
)
new_gen = (
    "\t# BytesGenerator.write() is hardcoded to ASCII-only regardless of\n"
    "\t# policy (confirmed by reading CPython's email/generator.py source)\n"
    "\t# - genuine Unicode in a payload (smart quotes, figure spaces, etc,\n"
    "\t# extremely common in real HTML email) crashes it no matter what.\n"
    "\t# The string Generator has no such restriction - flatten to that,\n"
    "\t# then encode the result as UTF-8 ourselves.\n"
    "\tstrbuf = io.StringIO()\n"
    "\tgen = email.generator.Generator(strbuf)\n"
    "\tgen.flatten(internal_msg)\n"
    "\tinmem_file = io.BytesIO(strbuf.getvalue().encode('utf-8'))\n"
)
if old_gen not in src:
    sys.exit("fix_eml_unicode_serialization.py: BytesGenerator block not found - upstream may have changed")
src = src.replace(old_gen, new_gen, 1)

path.write_text(src)
