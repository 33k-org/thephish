#!/usr/bin/env python3
"""
Build-time patch applied to the pinned ThePhish-NG commit (see Dockerfile).

Confirmed on a real deploy: if a forwarded email has no message/rfc822 (or
.eml-decoded application/octet-stream) attachment - i.e. it was forwarded
inline (a mail client's default "Forward"), rather than as an attachment -
app/services/list_emails.py silently drops it. It never appears in
/api/list or the UI, stays unread, and gets silently re-checked and
re-skipped on every future poll. The sender has no way to know their
report never actually got processed.

This patch sends the sender a one-time notice explaining the email needs
to be forwarded as an attachment, then marks the message seen so it isn't
re-checked forever. Deliberately bypasses TheHive/Cortex/Mailer_1_0
entirely and sends directly over SMTP using this mailbox's own IMAP
credentials (config['imap']) - there's no case/observable to hang a
Mailer responder action off for a submission that was never actually
processed, and creating a throwaway case/alert just to reuse Mailer_1_0
would add TheHive noise for something that isn't really an analysis
result.
"""
import pathlib
import sys

path = pathlib.Path("app/services/list_emails.py")
src = path.read_text()

old_imports = (
    "import email\n"
    "import base64\n"
    "import logging\n"
    "import traceback\n"
    "from typing import Optional, Any\n"
    "import bs4\n"
    "import magic\n"
    "from imapclient import IMAPClient\n"
    "from app.utils import imap_pool\n"
)
new_imports = old_imports + (
    "import smtplib\n"
    "import ssl\n"
    "from email.message import EmailMessage\n"
    "from email.utils import formatdate, make_msgid, parseaddr\n"
    "from app.utils import config as config_utils\n"
    "\n"
    "\n"
    "# Reuses this mailbox's own IMAP credentials to send a direct SMTP\n"
    "# notice - see this file's own docstring-equivalent comment in\n"
    "# mail-server/thephish/patches/notify_wrong_format.py for why this\n"
    "# bypasses TheHive/Cortex/Mailer_1_0 entirely.\n"
    "def notify_wrong_format(num, from_field):\n"
    "\tsender_address = parseaddr(from_field)[1]\n"
    "\tif not sender_address:\n"
    "\t\tlog.warning(\"Could not determine a sender address for message %s - skipping wrong-format notice\", num)\n"
    "\t\treturn\n"
    "\n"
    "\timap = config_utils.get()[\"imap\"]\n"
    "\t# Guard against a reply/notify loop: our own verdict/notification\n"
    "\t# emails, and our own wrong-format notices, land back in this same\n"
    "\t# mailbox whenever mail_to happens to be this mailbox's own address\n"
    "\t# (self-testing, or a real employee's mail_to somehow resolving\n"
    "\t# back to us) - none of those have an EML attachment either, so\n"
    "\t# without this check each one would trigger another notice, forever.\n"
    "\t# Confirmed live: this loop actually happened during testing.\n"
    "\tif sender_address.lower() == imap[\"user\"].lower():\n"
    "\t\tlog.info(\"Skipping wrong-format notice for message %s - sender is this mailbox itself (%s)\", num, sender_address)\n"
    "\t\treturn\n"
    "\n"
    "\tnotice = EmailMessage()\n"
    "\tnotice[\"From\"] = imap[\"user\"]\n"
    "\tnotice[\"To\"] = sender_address\n"
    "\tnotice[\"Subject\"] = \"Your submission could not be processed\"\n"
    "\tnotice[\"Date\"] = formatdate(localtime=True)\n"
    "\tnotice[\"Message-ID\"] = make_msgid()\n"
    "\tnotice.set_content(\n"
    "\t\t\"Hi,\\n\\n\"\n"
    "\t\t\"We received your forwarded email, but couldn't process it: the \"\n"
    "\t\t\"suspicious email needs to be attached as a file (.eml), not \"\n"
    "\t\t\"forwarded inline.\\n\\n\"\n"
    "\t\t\"Please use your mail client's \\\"Forward as attachment\\\" option \"\n"
    "\t\t\"(not the default \\\"Forward\\\") and resend.\\n\\n\"\n"
    "\t\t\"Thanks.\"\n"
    "\t)\n"
    "\n"
    "\tif imap[\"tlsinsecure\"] == \"yes\":\n"
    "\t\tctx = ssl._create_unverified_context()\n"
    "\telse:\n"
    "\t\tctx = ssl.create_default_context()\n"
    "\ttry:\n"
    "\t\twith smtplib.SMTP(imap[\"host\"], 587) as smtp:\n"
    "\t\t\tsmtp.starttls(context=ctx)\n"
    "\t\t\tsmtp.login(imap[\"user\"], imap[\"password\"])\n"
    "\t\t\tsmtp.send_message(notice)\n"
    "\t\tlog.info(\"Sent wrong-format notice to %s for message %s\", sender_address, num)\n"
    "\texcept Exception:\n"
    "\t\tlog.error(\"Failed to send wrong-format notice for message %s: %s\", num, traceback.format_exc())\n"
)
if old_imports not in src:
    sys.exit("notify_wrong_format.py: imports block not found - upstream may have changed, patch needs updating")
src = src.replace(old_imports, new_imports, 1)

old_tail = (
    "\t\tif (eml_attachment_found == True):\n"
    "\t\t\temail_info = {}\n"
    "\t\t\temail_info['mailUID'] = str(num)\n"
    "\t\t\temail_info['from'] = from_field\n"
    "\t\t\temail_info['subject'] = subject_field\n"
    "\t\t\temail_info['date'] = msg['Date']\n"
    "\t\t\temail_info['body'] = body\n"
    "\t\t\temail_info['attachedMail'] = attached_mail_subject\n"
    "\n"
    "\t\t\t# Problematic characters substitution\n"
    "\t\t\tfor key in email_info:\n"
    "\t\t\t\t# single quote\n"
    "\t\t\t\temail_info[key] = email_info[key].encode(\"unicode-escape\").decode().replace(r'\\x92', '\\'').encode().decode(\"unicode-escape\")\n"
    "\t\t\temails_info.append(email_info)\n"
    "\n"
    "\treturn emails_info\n"
)
new_tail = (
    "\t\tif (eml_attachment_found == True):\n"
    "\t\t\temail_info = {}\n"
    "\t\t\temail_info['mailUID'] = str(num)\n"
    "\t\t\temail_info['from'] = from_field\n"
    "\t\t\temail_info['subject'] = subject_field\n"
    "\t\t\temail_info['date'] = msg['Date']\n"
    "\t\t\temail_info['body'] = body\n"
    "\t\t\temail_info['attachedMail'] = attached_mail_subject\n"
    "\n"
    "\t\t\t# Problematic characters substitution\n"
    "\t\t\tfor key in email_info:\n"
    "\t\t\t\t# single quote\n"
    "\t\t\t\temail_info[key] = email_info[key].encode(\"unicode-escape\").decode().replace(r'\\x92', '\\'').encode().decode(\"unicode-escape\")\n"
    "\t\t\temails_info.append(email_info)\n"
    "\t\telse:\n"
    "\t\t\t# No EML attachment found - forwarded inline, nothing to\n"
    "\t\t\t# analyze. Notify the sender once, then mark it seen so it\n"
    "\t\t\t# isn't silently re-checked (and never surfaced anywhere)\n"
    "\t\t\t# on every future poll.\n"
    "\t\t\tnotify_wrong_format(num, from_field)\n"
    "\t\t\tconnection.add_flags([num], ['\\\\Seen'])\n"
    "\n"
    "\treturn emails_info\n"
)
if old_tail not in src:
    sys.exit("notify_wrong_format.py: retrieve_emails() tail not found - upstream may have changed, patch needs updating")
src = src.replace(old_tail, new_tail, 1)

path.write_text(src)
