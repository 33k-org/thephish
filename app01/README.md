# app01 - TheHive

TheHive (case management / alert triage) + its two required backends:
Cassandra (primary datastore, via JanusGraph) and Elasticsearch (search
index). This is the only host currently deployed in real life; the files
here are a best-effort reconstruction and **have not been verified against
what's actually running** - reconcile before treating this as the source
of truth. See the top-level README for why.

Sizing target: ~32GB RAM / 4-8 cores / SSD (StrangeBee's official
"production #2" profile, minus their optional nginx TLS-termination
container, which wasn't part of the original ask).

## What's here

- `docker-compose.yml` - cassandra + elasticsearch + thehive, no nginx/TLS
  termination (add your own reverse proxy in front if needed)
- `thehive/conf/application.conf` - mounted read-only into the container.
  Cortex/MISP connector modules are enabled (matches StrangeBee's own
  reference deployment) but no server is configured, so TheHive runs fine
  standalone. The `cortex`/`misp` blocks are commented out with a
  `TODO(app02)` marker for when app02 exists.
- `.env.example` - copy to `.env` (gitignored) and fill in real secrets.
  Never commit `.env`.

## First-time deploy

```bash
cp .env.example .env
# Edit .env: set UID/GID to `id -u`/`id -g`, generate ELASTICSEARCH_PASSWORD
# and THEHIVE_SECRET_KEY (e.g. `tr -dc 'A-Za-z0-9' </dev/urandom | head -c 64`)

docker compose up -d
```

Data/log directories (`cassandra/data`, `elasticsearch/data`,
`thehive/data`, `thehive/logs`, etc.) are created automatically as bind
mounts on first run and are gitignored - they live only on app01's disk.

TheHive listens on `:9000`. First login is `admin@thehive.local` /
`secret` - **change this immediately**.

On first login you'll see a banner about a 15-day "Platinum" trial
license - the Docker image ships with this by default. **It does not
automatically fall back to or request a Community license when the
trial expires** - you must proactively register a free Community
license via a StrangeBee account before the trial runs out, or TheHive
will be left without a valid license once it lapses. A Community
license is all this pipeline needs; no paid Enterprise tier is
required.

## Connecting app02 (Cortex) later

Once app02 is built, either:

1. Uncomment the `cortex` block in `thehive/conf/application.conf`, fill
   in app02's address, add `CORTEX_API_KEY` to `.env`, wire it into the
   `thehive` service's `environment:` in `docker-compose.yml`, and
   restart TheHive; or
2. Leave `application.conf` alone and configure it via the UI instead:
   **Platform management → Connectors → Cortex → Servers → Add** (this is
   what StrangeBee's own docs recommend as of TheHive 5).

Same pattern applies to the `misp` block for app02's MISP instance.

## Known gaps to reconcile against the real app01

- Exact TheHive/Cassandra/Elasticsearch versions actually running (this
  repo assumes TheHive 5.7.3 / Cassandra 4.1.11 / Elasticsearch 8.19.15 -
  StrangeBee's current pinned combination as of 2026-07).
  - **Note**: could not verify with certainty which major version (4.x
    vs 5.x) is deployed - you asked me to use best judgement, so this
    assumes current 5.x. If the real app01 is TheHive 4.x, the
    `application.conf` syntax differs and will need reworking.
- Whether Cassandra/Elasticsearch auth is actually configured the way
  this repo assumes (Elasticsearch `xpack.security` basic auth;
  Cassandra `PasswordAuthenticator` with default `cassandra`/`cassandra`
  superuser - StrangeBee's own reference compose doesn't override this).
- Whether a reverse proxy / TLS termination sits in front of TheHive in
  reality (not included here).
- Actual resource limits/JVM heap sizes in use, if they were tuned by
  hand rather than left at StrangeBee's defaults.
