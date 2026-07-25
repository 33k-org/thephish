# mail-server - Postfix/Dovecot + ThePhish-NG

Receives forwarded suspicious emails and hosts
[ThePhish-NG](https://github.com/dead-plant/ThePhish-NG), the web app that
orchestrates TheHive/Cortex/MISP and drives the actual verdict.

**Deployed for testing on app02's host** (not a dedicated third host yet) -
this is still a fully self-contained `docker-compose.yml` project, so it
can be moved to its own hardware later without changing anything here.
Confirmed working end-to-end on the real host - see "Validated end-to-end
on the real host" below.

## The actual verdict-email flow (important, non-obvious)

ThePhish-NG is **not** an automatic poll-and-reply loop, and it has **no
SMTP logic of its own**:

1. A human opens ThePhish-NG's web UI (`:8080`, no login) and clicks
   **List emails** - this polls the mailbox below over IMAP.
2. They pick one and click **Analyze** - this creates a TheHive case,
   extracts observables, and runs Cortex's enabled analyzers (including our
   Ollama one).
3. The verdict email is sent by **starting Cortex's stock `Mailer_1_0`
   responder** on the case's task via the TheHive/Cortex API - see
   `app02/README.md`'s "The Mailer responder". `Mailer_1_0` does the actual
   `smtplib` send.

So building this out means touching both this host (receive + human-driven
analysis trigger) *and* app02 (enabling/configuring the Mailer responder).
Confirmed by reading ThePhish-NG's actual source - there's no `smtplib`,
`MIMEText`, or similar anywhere in its own codebase.

Step 2 still needs a human (or a script) to call `/api/analysis` - there's
no polling loop that does this on its own. Step 3, once triggered, is now
fully automatic for **every** verdict including "Suspicious" - see
"Auto-resolve every verdict, not just Malicious/Safe" below (upstream's
own default only auto-replies for Malicious/Safe and leaves Suspicious
open for manual review).

## What's here

- `docker-compose.yml` - `mailserver` (Postfix + Dovecot, bundled) +
  `thephish` (our own build of ThePhish-NG).
- `thephish/Dockerfile` - ThePhish-NG has no Docker image or releases/tags
  of its own (checked 2026-07-22) - this pins a specific upstream commit
  SHA and builds it ourselves. Bump the `THEPHISH_NG_COMMIT` build arg
  deliberately to pick up upstream changes. Also applies three build-time
  patches (a one-line `sed`, plus two Python scripts under
  `thephish/patches/`) - see "A real gotcha: Ollama never actually runs
  automatically", "Auto-resolve every verdict", and "Notify the sender on
  the wrong forward format" below.
- `thephish/config-template/` - ThePhish-NG's config format is plain JSON
  with no env-var substitution support. `configuration.json` (the only file
  with secrets) is rendered from environment variables at container start
  by `render_config.py` (called from `entrypoint.sh`); the rest
  (`whitelist.json`, `analyzers_level_conf.json`, `logging_conf.json`) have
  no secrets and are copied verbatim. Keeps secrets in `.env` (gitignored)
  like everywhere else in this repo, instead of a hand-edited JSON file
  that risks getting committed.
  - `analyzers_level_conf.json` ships as `{}` here - it only remaps one
    analyzer's verdict levels into another's scale (e.g. "malicious" ->
    "info" for a noisy one); unlisted analyzers (all of ours) just keep
    their own reported level unchanged, confirmed by reading
    `app/utils/analyzer_levels.py`'s `map_level()`.
- `postfix-config/` - sender-domain allowlist for inbound mail on port 25 -
  see "Sender-domain allowlist" below. Tracked in git (unlike
  `mailserver/config`, which holds secrets/certs and is gitignored),
  layered into the same container path as individual file mounts.
- `.env.example` - copy to `.env` (gitignored) and fill in real values.

## A real gotcha found while building this: Postfix/Dovecot need TLS certs before they'll even start

`docker-mailserver`'s `SSL_TYPE=self-signed` doesn't generate a cert for
you - it expects `<FQDN>-key.pem`, `<FQDN>-cert.pem`, and
`demoCA/cacert.pem` to already exist under `mailserver/config/ssl/`, and
Dovecot refuses to start at all without them. For LAN-only testing, a
single self-signed cert used as its own CA is enough (see "First-time
deploy" below) - get a real cert (Let's Encrypt) once this is
internet-facing.

Separately: `docker-mailserver` also refuses to start Dovecot until **at
least one mailbox account exists**, and gives you exactly 120 seconds after
first start to create one before it shuts itself down - see "First-time
deploy".

## A real gotcha found on a real deploy: `MAIL_HOSTNAME` and the mailbox domain must be different

Setting `MAIL_HOSTNAME` and the mailbox's domain to the *same* value (e.g.
both `mail.pwned.email`) breaks inbound delivery. Postfix always adds its
own `$myhostname` (`MAIL_HOSTNAME`) to `mydestination` (local/system-user
delivery), so if that's also your virtual mailbox domain, Postfix can't
tell whether an address in that domain should be delivered locally (as a
Unix user) or virtually (as a docker-mailserver account) - it picks local,
finds no matching Unix user, and rejects with `550 5.1.1 ... User unknown
in local recipient table`, even though `setup email list` shows the
account existing fine.

Fix: use the conventional split - `MAIL_HOSTNAME` is the server's own FQDN
(`mail.pwned.email`), the mailbox address is under the **parent** domain
(`phishing@pwned.email`, not `phishing@mail.pwned.email`). Confirmed fixed
by recreating the mailbox account under the parent domain; `postconf -h
mydestination` no longer overlaps `postconf -h virtual_mailbox_domains`
(`cat /etc/postfix/vhost` inside the container) after the fix.

## A real gotcha found on a real deploy: Cortex's Mailer responder can't send through a self-signed cert

Cortex's stock `Mailer_1_0` responder (`cortexutils`/`smtplib`) uses
`ssl.create_default_context()` for STARTTLS with **no way to disable
verification** via its config - unlike everywhere else in this repo, there
is no `tlsinsecure`-style escape hatch here. Against `mailserver`'s
self-signed cert this fails closed in a confusing way: the cert
verification error is swallowed by Mailer's own fallback logic, which
retries over a *plaintext* connection - but `docker-mailserver`'s
submission port (587) mandates TLS before `AUTH` is even offered
(`smtpd_tls_security_level=encrypt` on that port only), so the fallback
also fails, surfacing as `SMTPNotSupportedError: SMTP AUTH extension not
supported by server` - a red herring that looks like an auth problem, not
a TLS trust problem. Also confirmed: docker-mailserver only copies a
`SSL_TYPE=self-signed` cert into its actual serving location
(`/etc/dms/tls/`) on the container's **first ever boot** - a plain
`docker compose restart` after regenerating the cert does *not* pick up
the new files; either `docker cp` them into `/etc/dms/tls/` and `postfix
reload`, or fully recreate the container.

Fix (three parts, all needed):

1. Generate the self-signed cert with a `subjectAltName` covering *both*
   the hostname and whatever address Cortex actually dials
   (`MAILER_SMTP_HOST` in `app02/.env` - an IP if there's no internal DNS
   yet), e.g.:
   ```bash
   openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
     -keyout "mailserver/config/ssl/${FQDN}-key.pem" \
     -out "mailserver/config/ssl/${FQDN}-cert.pem" \
     -subj "/CN=${FQDN}" \
     -addext "subjectAltName=DNS:${FQDN},IP:${MAILER_SMTP_HOST_IP}"
   ```
2. Build a small variant of Cortex's Mailer image that trusts this cert's
   CA and point the enabled responder at it (Cortex's own UI has no field
   for a responder's Docker image, so this is done once via API - see
   `app02/README.md`'s "The Mailer responder"):
   ```bash
   mkdir -p /tmp/mailer-ca-build && cd /tmp/mailer-ca-build
   cp path/to/mailserver/config/ssl/${FQDN}-cert.pem .
   cat > Dockerfile <<EOF
   FROM ghcr.io/thehive-project/mailer:1
   COPY ${FQDN}-cert.pem /usr/local/share/ca-certificates/mail-server.crt
   RUN update-ca-certificates
   EOF
   docker build -t thephish/mailer-ca:1 .
   ```
3. Whenever the cert is regenerated, both the mail server's `/etc/dms/tls/`
   copy *and* this image need rebuilding/refreshing - they'll silently
   drift out of sync otherwise.

This is a one-time deploy-time cost, not something `docker compose up`
handles by itself - reasonable for LAN testing with a self-signed cert;
switching to a real CA-issued cert (Let's Encrypt) once this is
internet-facing removes the need for the custom image entirely.

## A real gotcha found on a real deploy: Ollama never actually runs automatically

ThePhish-NG's own `app/services/run_analysis.py` only ever auto-triggers
**`Yara_3_0`, by hardcoded name**, on the forwarded email's file/EML
observable - unlike url/domain/mail/ip/hash observables, there is no
generic "run every enabled analyzer of this type" path for it. Since this
repo doesn't enable Yara, and our own `Ollama_Phishing_Analysis_1_0`
analyzer is also a file-type analyzer, it was **silently never triggered**
by the normal "Analyze" button - confirmed on a real end-to-end run:
case/observable creation and the Mailer responder all worked, but Cortex's
job history showed zero Ollama jobs tied to the new case, and the verdict
came back "Safe" purely because nothing had actually analyzed the email
content.

Fixed by patching that one condition at Docker build time (see
`thephish/Dockerfile`) to also match `Ollama_Phishing_Analysis_1_0`,
rather than opening the check up to every enabled file-type analyzer -
not all file analyzers are meaningful (or safe to run unattended) against
a raw `.eml`.

## Auto-resolve every verdict, not just Malicious/Safe

Upstream's `run_analysis.py` only auto-closes the case and auto-sends the
verdict email (via the Mailer responder) for **Malicious**/**Safe**
verdicts - **Suspicious** is deliberately left `InProgress` with a
placeholder task description
(`---> INSERT BODY OF THE E-MAIL TO SEND <---`), for a human to write and
send the reply by hand. Confirmed on a real deploy: a real forwarded
newsletter got verdicted "Suspicious" and then just sat there - not
hung, working as upstream intends, but not what this deployment wants.

This deployment wants the whole pipeline to run unattended end-to-end
regardless of verdict, always replying to whoever forwarded the email -
see `thephish/patches/auto_resolve_all_verdicts.py` (applied at Docker
build time, same mechanism as the Ollama patch above). Suspicious now
takes the same auto-resolve+notify path as Malicious/Safe, closing the
case with TheHive's `Indeterminate` resolution status (MISP export stays
Malicious-only, unchanged - see the patch script for the exact diff).

Confirmed on a real deploy with a deliberately ambiguous test email
(a legitimate-looking "account activity" notification): verdicted
Suspicious, "Notification mail sent" logged, case resolved as
`Indeterminate` - no manual intervention needed.

## Notify the sender on the wrong forward format

ThePhish-NG only ever recognizes a forwarded email if it finds a
`message/rfc822` (or `.eml`-decoded `application/octet-stream`) part
while walking the MIME structure - i.e. **forwarded as an attachment**.
If someone uses their mail client's default **"Forward"** instead (which
pastes the original as quoted text in the body - Gmail, Outlook, Apple
Mail all do this unless you explicitly pick "Forward as attachment"),
`app/services/list_emails.py` silently drops it: never listed, never
analyzed, no error anywhere, and it gets silently re-checked and
re-skipped forever on every future poll since it's never marked seen.
Confirmed on a real deploy - there's no existing notification for this
anywhere in ThePhish-NG's own code.

Patched via `thephish/patches/notify_wrong_format.py` (applied at Docker
build time, same mechanism as the other two patches above):
`list_emails.py` now sends the sender a one-time notice explaining the
email needs to be forwarded as an attachment, then marks the message seen
so it isn't rechecked forever. Deliberately **bypasses TheHive/Cortex/
Mailer_1_0 entirely** and sends directly over SMTP using this mailbox's
own IMAP credentials (`config['imap']`, read the same way
`app/utils/imap_pool.py` does) - there's no case or observable to hang a
Mailer responder action off for a submission that was never actually
processed, and creating a throwaway case/alert just to reuse `Mailer_1_0`
would add TheHive noise for something that isn't an analysis result.

Confirmed on a real deploy: an inline-forwarded test message correctly
triggered `Sent wrong-format notice to <sender> for message <uid>` in the
logs, the notice was delivered (mailbox size grew), and the message no
longer reappears in `/api/list` on subsequent polls.

## Sender-domain allowlist

Before exposing port 25 to the internet: **not being an open relay is not
the same as controlling who can send you mail.** This server was already
confirmed not to be an open relay (`mynetworks` empty, `permit_mynetworks
permit_sasl_authenticated defer_unauth_destination` in
`smtpd_relay_restrictions`, `reject_unauth_destination` in
`smtpd_recipient_restrictions` - an anonymous sender can only ever deliver
*to* this server's one mailbox, never relay *through* it). But by default
anyone on the internet can still send mail *to* `phishing@pwned.email`.

`postfix-config/sender-domain-allowlist` restricts that: only sender
domains listed there are accepted on port 25 (unauthenticated inbound) -
everything else is rejected outright with `554 5.7.1 ... Access denied`,
by design (deny-by-default, not a denylist). Wired in via
`postfix-config/postfix-main.cf`'s `dms_smtpd_sender_restrictions`
override (docker-mailserver's supported mechanism for extending
`main.cf` - see their "Override the Default Configs" docs).

Confirmed on a real deploy: a message from a domain not on the list gets
`Access denied` at the sender-restriction stage; a message from an
allowlisted domain passes that stage and falls through to the existing
SPF check (`reject`ed there instead, since it wasn't actually sent from
that domain's real mail infrastructure) - the two checks are independent
layers, both need to pass for a real forward to get through.

**Doesn't affect authenticated submission (port 587)** -
`permit_sasl_authenticated` is checked first in the restriction chain, so
Cortex's Mailer responder (and the `send_test_phish.py`-style test
pattern used during development) are unaffected regardless of sender
domain, since they authenticate as the mailbox account itself.

This also does **not** restrict what domain appears inside a *forwarded*
phishing email's own `From` header (the attacker's lookalike domain) -
that's the entire point of this mailbox. It only restricts who's allowed
to forward mail to us in the first place, i.e. the outer envelope sender.

To add a domain: append a line to `postfix-config/sender-domain-allowlist`
(`example.com OK`). No rebuild needed - it's a file mount, not baked into
an image - but **use `docker compose up -d mailserver --force-recreate`**,
not a plain `up -d` or `restart`. Confirmed on a real deploy: editing the
file via a tool that replaces it (e.g. `scp`, `sed -i`'s default temp-file
swap) changes its inode, which silently detaches it from a *single-file*
bind mount (unlike a directory mount, which follows the path) - the
running container keeps serving the old content with no error, until the
container is recreated so the mount re-resolves.

## First-time deploy

```bash
cp .env.example .env
# Edit .env: MAIL_HOSTNAME (this server's own FQDN, e.g. mail.example.com),
# MAILBOX_ADDRESS (under the PARENT domain, e.g. phishing@example.com -
# see the MAIL_HOSTNAME/mailbox-domain gotcha above)/MAILBOX_PASSWORD, and
# the THEHIVE_*/CORTEX_*/MISP_* values (API keys from app01/app02's own
# first-login steps - the TheHive one needs the org-admin profile, not
# analyst, for manageCaseTemplate - see app01/README.md).

# Create these yourself *before* the first `up` - same root-owned-bind-mount
# issue as cortex/jobs and cortex-elasticsearch elsewhere in this repo:
# Docker auto-creates missing bind-mount sources as root, before
# docker-mailserver's own entrypoint gets a chance to chown them.
mkdir -p mailserver/mail-data mailserver/mail-state mailserver/mail-logs \
  mailserver/config/ssl/demoCA

# Self-signed cert (LAN testing only - see the gotchas above). Replace
# mail.example.test with your real MAIL_HOSTNAME, and the IP with whatever
# MAILER_SMTP_HOST will be set to in app02/.env.
FQDN=mail.example.test
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout "mailserver/config/ssl/${FQDN}-key.pem" \
  -out "mailserver/config/ssl/${FQDN}-cert.pem" \
  -subj "/CN=${FQDN}" \
  -addext "subjectAltName=DNS:${FQDN},IP:203.0.113.10"
cp "mailserver/config/ssl/${FQDN}-cert.pem" mailserver/config/ssl/demoCA/cacert.pem

docker compose build thephish
docker compose up -d mailserver

# Within 120s of the mailserver container starting - create the one mailbox
# account. Same address used for both IMAP (ThePhish-NG polling) and SMTP
# submission (Cortex's Mailer responder) - see MAILBOX_ADDRESS in .env.
docker exec mailserver setup email add "$MAILBOX_ADDRESS" "$MAILBOX_PASSWORD"

docker compose up -d thephish
```

ThePhish-NG's UI is then at `http://<this-host>:8080` (no login - see
"Known gaps"). Point app02's Mailer responder at this host's `:587` with
the same mailbox credentials, and build/enable the CA-trusting Mailer image
- see the gotcha above and `app02/README.md`'s "The Mailer responder".

### Validated end-to-end on the real host

Confirmed on the real deploy (app02, 2026-07-25) with a hand-crafted
forwarded-phishing test email (fake account-suspension lure, `.eml`
attachment): SMTP delivery into the mailbox -> ThePhish-NG's `/api/list`
parsed it correctly (subject, attached EML) -> `/api/analysis` created a
real TheHive case, extracted observables (sender address, lookalike
domain, phishing URL) -> Cortex ran the Ollama analyzer on the attached
EML (after the `run_analysis.py` patch above) -> Cortex's `Mailer_1_0`
responder sent both the "being analyzed" notification and the final
verdict email, confirmed delivered via `postfix/lmtp` logs and mailbox
size growth. All three of the gotchas above were found and fixed during
this run.

Earlier, isolated local validation (before a real TheHive/Cortex backend
was wired up): built both images, brought the stack up, created a test
mailbox account, confirmed ThePhish-NG's homepage (200) and `/api/list`
against a real SMTP-delivered test message.

One thing that tripped up test traffic but won't affect real forwarded
email: `docker-mailserver`'s bundled amavis rejects messages missing
standard headers (`Date`, `Message-ID`) as malformed - a hand-crafted test
message needs them explicitly; every real mail client already sends them.

Not yet validated against a real internet-facing setup (DNS MX record, a
real TLS cert, SPF/DKIM/DMARC) - inbound SPF checking on this server
correctly rejected test messages spoofing an external domain's `From`
address during testing, which is expected/correct, but means real
employees must actually forward through their own real mail
infrastructure, not a hand-crafted test client, for delivery to succeed.

## Known gaps not yet configured

- **No auth on ThePhish-NG's web UI at all** - fine for LAN-only testing,
  but put a reverse proxy with auth in front before this is reachable from
  anywhere less trusted (same "bring your own reverse proxy" stance already
  taken for TheHive/MISP in app01/app02).
- **Not internet-facing yet** - no DNS MX record, no real TLS cert
  (self-signed only), no SPF/DKIM/DMARC records published. Fine for testing
  forwards from inside the LAN; needed before real employees can forward
  mail from outside it.
- **`docker-mailserver`'s spam/AV scanning is minimal** -
  `ENABLE_SPAMASSASSIN=0`/`ENABLE_CLAMAV=0` for now (this mailbox only ever
  receives deliberately-forwarded suspicious mail, so aggressive filtering
  would be counterproductive) - revisit if this mailbox ever needs to be
  more than a dedicated phishing-triage address.
