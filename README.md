# Self-hosted phishing/spam triage pipeline

Users forward suspicious emails (as an EML attachment) to a dedicated
mailbox. An analyst opens [ThePhish-NG](https://github.com/dead-plant/ThePhish-NG)'s
web UI, lists the forwarded emails, and triggers analysis: it extracts
observables and orchestrates analysis via Cortex + TheHive + MISP -
including a custom Cortex analyzer that sends the email content to a local
Ollama instance for LLM-based phishing/social-engineering analysis, as a
signal alongside the existing threat-intel checks. The verdict is emailed
back to whoever forwarded the message, via Cortex's own Mailer responder
(see `mail-server/README.md` for why that split matters).

## Hosts

| Host | Role | Status |
|---|---|---|
| GPU box | Ollama (Qwen3 14B/32B), A5000 24GB VRAM, `0.0.0.0:11434` firewalled to app02 only | already built (outside this repo) |
| `app01/` | TheHive + Cassandra + Elasticsearch | already built, being reconciled into this repo |
| `app02/` | Cortex (+ its own Elasticsearch) + MISP + MariaDB + Redis + the Ollama analyzer | deployed, connected to app01 |
| `mail-server/` | Postfix + Dovecot + ThePhish-NG | built and validated locally - not yet deployed (planned: co-located on app02's host for testing) |

Each host folder is self-contained: its own `docker-compose.yml`, its own
`.env.example` (copy to `.env`, fill in real secrets, never commit `.env`
- see `.gitignore`).

## Deployment order and dependencies

1. **app01** (TheHive) - no dependency on anything else. TheHive's Cortex
   and MISP connector modules are enabled but unconfigured, so it runs
   standalone without erroring on a missing Cortex connection.
2. **app02** (Cortex + MISP) - depends on the GPU box being reachable
   (the Ollama analyzer calls out to it) and needs app01's TheHive URL +
   API key entered into MISP/Cortex config where relevant. Once app02 is
   up, go back into app01's `thehive/conf/application.conf` and either
   uncomment the `cortex`/`misp` blocks or configure the connection via
   TheHive's UI (Platform management → Connectors).
3. **mail-server** (ThePhish-NG + Postfix/Dovecot) - depends on both app01
   and app02 being reachable (needs TheHive + Cortex + MISP API keys and
   URLs), and app02 needs its Mailer responder pointed back at this host
   once it's up (see `app02/README.md`'s "The Mailer responder"). Built
   last, for testing purposes co-located on app02's host rather than
   dedicated hardware.

## Version compatibility notes

- **TheHive 5** moved to a "freemium/private-source" licensing model in
  2024 (no longer developed fully in the open), but still ships a free
  Community license and a public Docker image (`strangebee/thehive:5.x`)
  usable for self-hosting. TheHive 4 is the last fully open-source (AGPL)
  version and has been EOL since Dec 2022.
- **TheHive requires both Cassandra and Elasticsearch** - there's no
  supported Elasticsearch-only mode, in either TheHive 4 or 5.
- **The original [ThePhish](https://github.com/emalderson/ThePhish) is
  effectively abandoned** (last commit Aug 2024), hard-pinned to TheHive
  4.1.9 + Cortex 3.1.1 (both EOL), and built on `thehive4py`/`cortex4py`
  v1.x clients that don't speak TheHive 5's rewritten API - it will not
  work against a TheHive 5 + Cortex 4 backend as-is.
- This repo instead targets **TheHive 5.x + Cortex 4.x +
  [ThePhish-NG](https://github.com/dead-plant/ThePhish-NG)** (an actively
  maintained fork that explicitly adds TheHive 5 support via
  `thehive4py`/`cortex4py` 2.1.0). Its own setup docs are incomplete
  ("coming soon" as of this writing) and it ships no Docker image or
  releases/tags - `mail-server/thephish/Dockerfile` builds it from a
  pinned commit SHA instead. It also has no SMTP logic of its own; see
  `mail-server/README.md` for how verdict emails actually get sent.
- Versions currently pinned in `app01/.env.example`: TheHive 5.7.3,
  Cassandra 4.1.11, Elasticsearch 8.19.15 - StrangeBee's own currently
  pinned combination.
- Versions currently pinned in `app02/.env.example`: Cortex 4.1.0 (its own
  Elasticsearch 8.19.15, separate from app01's), MISP core v2.5.44 +
  misp-modules v3.0.9 (MISP's own currently recommended combination),
  MariaDB 10.11, Valkey 7.2.

## Current status

- `app01/` - deployed to the real host and confirmed working (TheHive +
  Cassandra + Elasticsearch all healthy, `/api/status` returning 200).
- `app02/` - deployed to the real host: Cortex + MISP both healthy and
  connected to app01 (Platform management → Connectors shows both). The
  Ollama analyzer (`ollama-analyzer/`) is enabled in Cortex and confirmed
  working end-to-end against the real GPU box (`qwen3:14b`), verdict +
  reasoning coming back correctly on a real submitted email.
- `mail-server/` - built and validated locally (both images build, IMAP
  login + a real SMTP-delivered test `.eml` round-tripped correctly through
  ThePhish-NG's `/api/list`), but not yet deployed to the real host or
  tested against real TheHive/Cortex credentials or a full
  Cortex-driven analysis + Mailer responder send.
