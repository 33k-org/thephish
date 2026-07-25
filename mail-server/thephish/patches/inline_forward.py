"""New module, copied into app/utils/inline_forward.py at Docker build
time (see the Dockerfile) - not part of upstream ThePhish-NG.

Best-effort recovery of a forwarded email from inline-quoted body text,
for mail clients whose default "Forward" pastes the original as quoted
text rather than attaching it as .eml/message-rfc822 (Gmail, Outlook,
Apple Mail all do this by default - see mail-server/README.md's "Recover
forwarded emails from inline quoting" section for why this exists).

Deliberately narrow: recognizes a handful of common forward-marker
formats and gives up (returns None) if none match, rather than guessing
wrong and silently mis-attributing content to the wrong sender. Used by
both app/services/list_emails.py (to decide whether an inline-forwarded
email is listable at all) and app/services/case_from_email.py (to
actually build the "attachment" analyzed later) - see
patches/enable_inline_forward.py for where those are wired in.
"""
import email
import re
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

import bs4

# Ordered roughly by how unambiguous each marker is - checked in the order
# below isn't actually significant since we take whichever match ends
# latest in the text (see extract()), covering nested/chained forwards by
# always preferring the innermost (most recent) original message.
_FORWARD_MARKERS = [
	r'-{2,}\s*Forwarded message\s*-{2,}',  # Gmail
	r'-{2,}\s*Original Message\s*-{2,}',   # Outlook (plain text)
	r'Begin forwarded message:',           # Apple Mail
]


def get_plaintext_body(msg):
	"""Best-effort plain-text body extraction - text/plain preferred,
	falling back to a stripped-down text/html. Returns None if neither
	part type is present."""
	for part in msg.walk():
		if part.get_content_type() == 'text/plain':
			try:
				return part.get_payload(decode=True).decode()
			except UnicodeDecodeError:
				return part.get_payload(decode=True).decode('ISO-8859-1')
	for part in msg.walk():
		if part.get_content_type() == 'text/html':
			try:
				html = part.get_payload(decode=True).decode()
			except UnicodeDecodeError:
				html = part.get_payload(decode=True).decode('ISO-8859-1')
			return bs4.BeautifulSoup(html, 'html.parser').get_text()
	return None


def extract(outer_msg, body_text=None):
	"""Find the LAST recognized forward marker in body_text (computed from
	outer_msg via get_plaintext_body() if not given) and synthesize an
	email.message.Message from everything after it - "cut the last forward
	and create the eml file from the rest". Returns None if no marker is
	found or nothing usable remains after it.
	"""
	if body_text is None:
		body_text = get_plaintext_body(outer_msg)
	if not body_text:
		return None

	last_end = -1
	for pattern in _FORWARD_MARKERS:
		for m in re.finditer(pattern, body_text, re.IGNORECASE):
			if m.end() > last_end:
				last_end = m.end()
	if last_end == -1:
		return None

	remainder = body_text[last_end:].lstrip('\r\n')
	if not remainder.strip():
		return None

	# Most forward markers are immediately followed by a header block
	# ("From: ...\nDate: ...\nSubject: ...\n\nbody") - which is just an
	# RFC822 message, so Python's own parser handles it directly rather
	# than us hand-rolling a header regex.
	candidate = email.message_from_string(remainder)
	if not (candidate.get('Subject') or candidate.get('From')):
		# No recognizable header block - treat the whole remainder as the
		# body instead, with placeholder headers.
		candidate = EmailMessage()
		candidate['Subject'] = outer_msg.get('Subject', '(no subject)')
		candidate['From'] = 'unknown@unknown'
		candidate.set_content(remainder)

	if not candidate.get('Date'):
		candidate['Date'] = outer_msg.get('Date', formatdate(localtime=True))
	if not candidate.get('Message-ID'):
		candidate['Message-ID'] = make_msgid()

	return candidate
