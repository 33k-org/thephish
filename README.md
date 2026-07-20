# Self-hosted phishing/spam triage pipeline

Users forward suspicious emails (as an EML attachment) to a dedicated
mailbox. [ThePhish](https://github.com/emalderson/ThePhish) picks them up,
extracts observables, and orchestrates analysis via Cortex + TheHive +
MISP - including a custom Cortex analyzer that sends the email content to
a local Ollama instance for LLM-based phishing/social-engineering
analysis, as a signal alongside the existing threat-intel checks. The
verdict is emailed back to whoever forwarded the message.

## Hosts

| Host | Role | Status |
|---|---|---|
| GPU box | Ollama (Qwen3 14B/32B), A5000 24GB VRAM, `0.0.0.0:11434` firewalled to app02 only | already built (outside this repo) |
| `app01/` | TheHive + Cassandra + Elasticsearch | already built, being reconciled into this repo |
| `app02/` | Cortex + MISP + MariaDB + Redis + the Ollama analyzer | not yet built |
| `mail-server/` | Postfix + Dovecot + ThePhish | not yet built |

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
3. **mail-server** (ThePhish + Postfix/Dovecot) - depends on both app01
   and app02 being reachable (needs TheHive + Cortex + MISP API keys and
   URLs). Built last.

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
  ("coming soon" as of this writing), so expect more hands-on trial and
  error when `mail-server/` gets built.
- Versions currently pinned in `app01/.env.example`: TheHive 5.7.3,
  Cassandra 4.1.11, Elasticsearch 8.19.15 - StrangeBee's own currently
  pinned combination. Cortex/MISP versions for `app02/` haven't been
  chosen yet.

## Current status

Only `app01/` has real content, and it's **unverified** against what's
actually running on the live app01 host (this environment has no
filesystem access to any of the servers - everything here was
reconstructed from StrangeBee's official reference deployment). Reconcile
`app01/` first. `app02/`, `mail-server/`, and `ollama-analyzer/` are
scaffolding only.
