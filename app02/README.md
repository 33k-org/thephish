# app02 - Cortex + MISP

Cortex (analysis orchestration, including the custom Ollama analyzer - see
`../ollama-analyzer/`) + MISP (threat-intel platform), plus each one's own
backends: Cortex gets its own dedicated Elasticsearch instance (not shared
with app01's TheHive), MISP gets MariaDB (its database) and Valkey/Redis
(its cache). Validated locally end-to-end (all six containers healthy,
`/api/status` and `/users/heartbeat` both responding) and deployed to the
real app02 host, connected to app01.

Sizing target: modest by design - Cortex + its ES together aim for ~4-5GB
RAM, the MISP stack (core + modules + db + redis) another ~2-3GB. Adjust
the `deploy.resources.limits` in `docker-compose.yml` to match app02's
actual specs.

## What's here

- `docker-compose.yml` - cortex-elasticsearch + cortex + misp-redis +
  misp-db + misp-modules + misp-core, plus a build-only
  `ollama-analyzer-image` service (see "The Ollama analyzer" below). No TLS
  termination in front (MISP's own image already serves HTTPS itself via a
  bundled nginx + self-signed cert - see "MISP's self-signed cert" below).
- `cortex/conf/application.conf` - mounted read-only. Pulls StrangeBee's
  official analyzer/responder catalog (Docker images, fetched by Cortex
  itself at runtime) alongside a local one for our own Ollama analyzer, and
  pre-fills API keys/config for all five enabled analyzers (VirusTotal,
  AbuseIPDB, URLhaus, urlscan.io, Ollama) from `.env`.
- `.env.example` - copy to `.env` (gitignored) and fill in real secrets.
  Never commit `.env`.
- `../ollama-analyzer/` - the custom analyzer itself (source, Dockerfile,
  catalog JSON) - see "The Ollama analyzer" below.

## A real gotcha found while building this: Cortex and `/var/run/docker.sock`

Cortex's "docker" job runner (how it executes analyzers/responders, since
we're running our own custom Ollama analyzer as a container rather than a
bare-metal script) needs the host's Docker socket bind-mounted in so it can
launch each analyzer as a sibling container. Cortex's own entrypoint runs
as root and unconditionally does `chown cortex:cortex /var/run/docker.sock`
on every start - and because a bind mount shares the same inode as the
host file, **this reassigns the host's own `/var/run/docker.sock` group
ownership**, not just the copy inside the container.

Left at its default, this locks out any host user managing Docker via the
`docker` group instead of root (confirmed by reproducing it locally - it
locked this environment's own `docker` CLI out mid-build). The fix is in
`docker-compose.yml`: the `cortex` service's `command:` passes
`--daemon-user ${UID}:${DOCKER_GID}`, where `DOCKER_GID` (set in `.env`)
is the *host's* `docker` group GID (`getent group docker | cut -d: -f3`).
That makes Cortex's chown target the same group the host's Docker CLI
users are already in, instead of some unrelated default GID. Verified
locally across a full `docker compose down && docker compose up -d` cold
restart - the host socket's group stayed put.

**Get `DOCKER_GID` right in `.env` before first deploy on app02** - if you
skip it (or get the GID wrong), you'll likely lose `docker`-group CLI
access to app02 the moment the cortex container starts, and will need
`sudo chown root:docker /var/run/docker.sock` (or `sudo systemctl restart
docker`) to recover.

## A real gotcha found while building this: `--no-config` silently discards `--job-directory`

Cortex's "docker" job runner needs to know two paths for the shared jobs
directory: the container-internal one (`job.directory`) and the
absolute-host one (`job.dockerDirectory`, needed because Cortex spawns each
analyzer/responder as a *sibling* container via the host's Docker socket -
the daemon resolves bind-mount sources against the host filesystem, not
from inside Cortex's own container). The obvious way to set these looks
like the `--job-directory`/`--docker-job-directory` CLI flags - but Cortex's
own entrypoint script only writes those flags' values into a config file it
generates itself, and that generation is skipped entirely when `--no-config`
is passed (which this compose file's `cortex` service does, for other
reasons). With `--no-config`, those two flags are silently discarded and
`job.directory`/`job.dockerDirectory` fall back to their default
(`java.io.tmpdir`, plain `/tmp`) - which matches neither of our bind mounts.

Confirmed on a real deploy: jobs failed with cortexutils falling back to
(empty) stdin, same symptom as the root-owned-`cortex/jobs` bug below but a
different cause - the failing job's `docker compose logs cortex` showed
`volumes : /tmp/cortex-job-<id>-<n>`, with no `cortex-jobs` segment at all,
proving Cortex never pointed at the right directory to begin with. Both
bugs had to be fixed for real jobs to work: the root-owned-directory one
(below) blocks it even once Cortex points at the right place, and this one
means Cortex wasn't pointing at the right place at all. Fixed by setting
`job.directory`/`job.dockerDirectory` directly in
`cortex/conf/application.conf` instead of relying on the CLI flags -
see the comment there.

## First-time deploy

```bash
cp .env.example .env
# Edit .env: set UID/GID (`id -u`/`id -g`), DOCKER_GID
# (`getent group docker | cut -d: -f3`), CORTEX_JOBS_DIR (the *absolute*
# host path to this app02/cortex/jobs directory - see its comment in
# .env.example for why it can't be relative), and generate the various
# *_PASSWORD / *_SECRET_KEY / *_PASSPHRASE values (e.g.
# `tr -dc 'A-Za-z0-9' </dev/urandom | head -c 64`).

# Create cortex/jobs yourself *before* the first `up` - if Docker has to
# auto-create it as a bind-mount target, it does so as root, and Cortex's
# own process (running as your UID via --daemon-user) then can't create
# per-job subdirectories in it. Confirmed on a real deploy: jobs silently
# failed with cortexutils falling back to (empty) stdin, because the
# per-job folder Cortex wrote never made it into the spawned analyzer
# container - root-owned parent, permission denied, no error surfaced
# until you dig into `docker compose logs cortex`.
mkdir -p cortex/jobs

# First `up` will fail cortex-elasticsearch with "Error opening log file
# 'gc.log': Permission denied" - same root-owned-bind-mount issue app01's
# elasticsearch hits (confirmed on a real fresh app02 deploy, not just
# locally). Docker creates ./cortex-elasticsearch/{data,logs} as root on
# first run, before the image's own entrypoint gets a chance to chown them
# for the `user: "${UID}:0"` override. Fix, then retry:
docker compose up -d
sudo chown -R "${UID}:0" cortex-elasticsearch
chmod -R g+rwX cortex-elasticsearch
docker compose up -d
```

Data/log bind-mount directories (`cortex-elasticsearch/data`,
`misp/db-data`, etc.) are created automatically on first run and are
gitignored - they live only on app02's disk. `cortex/jobs` is the one
exception - create it yourself as shown above, for the reason given there.

### Cortex - first login

Cortex listens on `:9001`. Log in, then:

1. **Build the Ollama analyzer's image first** (it isn't pulled from any
   registry - see "The Ollama analyzer" below):
   `docker compose build ollama-analyzer-image`.
2. **Organization → Analyzers**: enable the analyzers you want. The four
   stock ones' API keys (VirusTotal, AbuseIPDB, URLhaus, urlscan.io) are
   pre-filled from `.env` if set - leave any blank to skip enabling that
   one. Free-tier signup: [virustotal.com](https://www.virustotal.com/gui/join-us),
   [abuseipdb.com](https://www.abuseipdb.com/register),
   [urlhaus.abuse.ch](https://urlhaus.abuse.ch/), [urlscan.io](https://urlscan.io/user/signup).
   `Ollama_Phishing_Analysis` should also be listed (from the local catalog
   directory, not StrangeBee's) with `ollama_host`/`ollama_port`/`model`
   pre-filled from `.env` - enable it too.
3. **Organization → Users**: create a non-admin user for TheHive to
   authenticate as, then generate its API key - this is what goes into
   app01's `CORTEX_API_KEY`.

### MISP - first login

MISP listens on `:9443` (HTTPS, self-signed cert - see below). Default
login is `admin@thephish.local` / the value you set for
`MISP_ADMIN_PASSWORD` - **change this immediately** if you left it as a
generated placeholder.

**`MISP_BASE_URL` must include `:9443`.** Confirmed on a real deploy: leave
the port off and MISP's own redirects send you to `https://<host>` with
its implicit `:443`, which nothing is listening on (we mapped container
443 to host 9443) - looks exactly like a hung/broken TLS connection, not a
redirect problem. Fix by setting it correctly in `.env` and recreating:
`docker compose up -d misp-core`.

Default feeds ship **disabled** - the `FETCH_FEED_INTERVAL`/
`CRON_PULLALL`/etc. env vars only control *scheduling*, they don't enable
any feed themselves. To turn on the community feeds decided on for this
deploy: **Sync Actions → List Feeds**, enable the ones you trust (e.g. the
CIRCL OSINT feed, abuse.ch feeds), then optionally trigger an immediate
`Fetch and store all feed data` instead of waiting for the next scheduled
pull.

Once you have a use for it, generate an API key under your user profile -
this is what goes into app01's `MISP_API_KEY`.

### The Ollama analyzer

`../ollama-analyzer/Ollama/` is our own custom analyzer (not part of
StrangeBee's catalog), discovered via a second entry in
`cortex/conf/application.conf`'s `analyzer.urls` that points at a local
directory (`/opt/cortex/analyzers-local`, bind-mounted from
`../ollama-analyzer`) instead of a URL - Cortex supports both. It sends a
submitted `.eml` file's headers + body to the GPU box's Ollama instance
and asks for a phishing/social-engineering verdict as JSON.

Its Docker image is never pulled from a registry - build it locally with
`docker compose build ollama-analyzer-image` (the
`ollama-analyzer-image` service in `docker-compose.yml` exists solely for
this; it's never started, since Cortex launches the image itself as a
sibling container via docker.sock). Cortex will still attempt a `docker
pull` before each run (`docker.autoUpdate` defaults to true) since it has
no way to know the image is local-only - this fails harmlessly and falls
back to the already-built local image (confirmed by reading Cortex's own
`DockerJobRunnerSrv`/`DockerClient` source: the pull's result is discarded,
and the image-exists check that actually gates execution matches on the
image name regardless of where it came from). Rebuild with the same
command after editing anything under `../ollama-analyzer/Ollama/`, then
use Cortex's UI (**Organization → Analyzers → refresh**) or restart Cortex
to pick up any change to `Ollama.json` itself.

**Qwen3 "thinks" by default** - if you point `model` at a reasoning model
(this pipeline's target: Qwen3 14B/32B) with Ollama's default settings, the
JSON verdict ends up in Ollama's `thinking` field instead of `response`,
which comes back empty (confirmed by testing live against a real Qwen3
instance). The analyzer sends `"think": false` to avoid this - if you swap
in a different reasoning model, verify it still respects that flag.

### MISP's self-signed cert

MISP's own image terminates TLS itself via a bundled nginx + a self-signed
cert generated at first boot (matches the official image's default - no
TLS termination was added in front of it here, same "bring your own reverse
proxy if you want one" stance as app01 takes with TheHive). Cortex/TheHive
connecting to it later will need to either trust/import that cert or skip
verification for an internal-only MISP instance - regenerate the cert to
match app02's real hostname once that's fixed, or replace it entirely by
mounting your own into `./misp/ssl/`.

## Known gaps not yet configured

- **Outbound mail from MISP** isn't wired up (no SMTP relay container) -
  MISP will log failures if it tries to send notification emails, but this
  isn't fatal. Revisit once `mail-server/` exists.
- **Feed sync depends on app02 having outbound internet access** on 443
  (to reach feed sources) and to `catalogs.download.strangebee.com` (for
  Cortex's own analyzer/responder catalog, and to pull each enabled
  analyzer's Docker image from its own registry - mostly hub.docker.com).
  Confirm app02's firewall allows this before first deploy.
- ~~The Ollama analyzer hasn't been run against the real GPU box yet~~ -
  confirmed working: enabled in Cortex, run against a real submitted email,
  correct verdict/reasoning came back using `qwen3:14b` on the real GPU
  box.

## Connecting app01 (TheHive) once this is confirmed working

Go back into `app01/thehive/conf/application.conf` and either uncomment
the `cortex`/`misp` blocks (filling in app02's real address and the API
keys generated above), or configure both via TheHive's UI instead
(**Platform management → Connectors**) - see app01's README for the same
choice laid out in more detail.
