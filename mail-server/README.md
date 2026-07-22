# mail-server - Postfix/Dovecot + ThePhish-NG

Receives forwarded suspicious emails and hosts
[ThePhish-NG](https://github.com/dead-plant/ThePhish-NG), the web app that
orchestrates TheHive/Cortex/MISP and drives the actual verdict.

**Deployed for testing on app02's host** (not a dedicated third host yet) -
this is still a fully self-contained `docker-compose.yml` project, so it
can be moved to its own hardware later without changing anything here.

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

## What's here

- `docker-compose.yml` - `mailserver` (Postfix + Dovecot, bundled) +
  `thephish` (our own build of ThePhish-NG).
- `thephish/Dockerfile` - ThePhish-NG has no Docker image or releases/tags
  of its own (checked 2026-07-22) - this pins a specific upstream commit
  SHA and builds it ourselves. Bump the `THEPHISH_NG_COMMIT` build arg
  deliberately to pick up upstream changes.
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

## First-time deploy

```bash
cp .env.example .env
# Edit .env: MAIL_HOSTNAME, MAILBOX_ADDRESS/MAILBOX_PASSWORD, and the
# THEHIVE_*/CORTEX_*/MISP_* values (API keys from app01/app02's own
# first-login steps).

# Create these yourself *before* the first `up` - same root-owned-bind-mount
# issue as cortex/jobs and cortex-elasticsearch elsewhere in this repo:
# Docker auto-creates missing bind-mount sources as root, before
# docker-mailserver's own entrypoint gets a chance to chown them.
mkdir -p mailserver/mail-data mailserver/mail-state mailserver/mail-logs \
  mailserver/config/ssl/demoCA

# Self-signed cert (LAN testing only - see the gotcha above). Replace
# mail.example.test with your real MAIL_HOSTNAME.
FQDN=mail.example.test
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout "mailserver/config/ssl/${FQDN}-key.pem" \
  -out "mailserver/config/ssl/${FQDN}-cert.pem" \
  -subj "/CN=${FQDN}"
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
the same mailbox credentials - see `app02/README.md`'s "The Mailer
responder".

### Validated locally

Built both images, brought the stack up, created a test mailbox account,
confirmed ThePhish-NG's homepage (200) and `/api/list` (clean `[]`, proving
IMAP login succeeded against the self-signed cert with
`IMAP_TLS_INSECURE=yes`). Then sent a real SMTP message with a `.eml`
attachment (mimicking a forwarded suspicious email) directly into the
mailbox and confirmed `/api/list` picked it up correctly, including parsing
the attached email's subject.

One thing that tripped up the test traffic but won't affect real forwarded
email: `docker-mailserver`'s bundled amavis rejects messages missing
standard headers (`Date`, `Message-ID`) as malformed - a hand-crafted test
message needs them explicitly; every real mail client already sends them.

Not yet validated against a real internet-facing setup (DNS MX record, a
real TLS cert, SPF/DKIM/DMARC) or against a real Cortex/TheHive-driven
analysis run (the local test above only exercised IMAP receive/list, not
`/api/analysis` - that needs real `app01`/`app02` credentials, not the
placeholder ones used for this local test).

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
