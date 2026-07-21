# ollama-analyzer

A custom Cortex analyzer that sends a submitted `.eml` file's headers and
body to the GPU box's Ollama instance (Qwen3 14B/32B) and asks for a
phishing/social-engineering verdict, as a signal alongside app02's stock
threat-intel analyzers (VirusTotal, AbuseIPDB, URLhaus, urlscan.io).

Runs on app02, launched by Cortex itself as a sibling container via its
Docker job runner - see `app02/README.md`'s "The Ollama analyzer" section
for how it's wired in, built, and enabled, and "Cortex and
`/var/run/docker.sock`" for why that job runner needs care on this host.

## What's here

- `Ollama/Ollama.json` - the analyzer's Cortex catalog definition
  (`dataTypeList: ["file"]`, config items for `ollama_host`/`ollama_port`/
  `model`/`timeout`). Discovered by Cortex via a local-directory catalog
  entry, not a URL - see `app02/cortex/conf/application.conf`.
- `Ollama/ollama_analyzer.py` - the analyzer itself, built on
  [`cortexutils`](https://github.com/TheHive-Project/cortexutils). Parses
  the submitted `.eml` with Python's `email` module (prefers the
  `text/plain` part, falls back to a crude HTML-tag strip), prompts Ollama
  for a JSON verdict (`malicious`/`suspicious`/`safe` + confidence +
  reasons), and reports it with a matching Cortex taxonomy level.
- `Ollama/Dockerfile` / `Ollama/requirements.txt` - builds a small
  `python:3.12-slim` image with `cortexutils` + `requests`. Never pulled
  from a registry - built locally on app02 (see `app02/docker-compose.yml`'s
  `ollama-analyzer-image` service) and referenced by that exact tag in
  `Ollama.json`'s `dockerImage` field.

## Validated so far

- The analyzer script + Dockerfile, end-to-end: built the image locally,
  hand-built a `/job` directory exactly as Cortex's `DockerJobRunnerSrv`
  does (input.json + a sample phishing `.eml`, no container args, default
  bridge networking), ran it against a real Qwen3 instance, and got back a
  correctly-parsed verdict. Repeated with a benign email to confirm it
  doesn't just always say "malicious".
- Cortex's own worker discovery: brought up a real Cortex 4.1.0 against
  this repo's `docker-compose.yml`/`application.conf`, and its log showed
  `New worker list: Ollama_Phishing_Analysis 1.0` - confirming the
  local-directory catalog entry, the bind mount, and `Ollama.json` are all
  read correctly.

**Not yet validated**: against the real GPU box (only tested against a
different local Ollama instance) - confirm `OLLAMA_HOST`/`OLLAMA_PORT`
reachability and firewall rules on the real app02 deploy.

## A real gotcha found while building this: Qwen3 "thinks" by default

Ollama's `/api/generate` splits reasoning models' output into a `thinking`
field and a `response` field. Left at its default, Qwen3 puts its entire
JSON answer inside `thinking` and `response` comes back empty - silently
breaking this analyzer (confirmed live: `response: ""` against a real
Qwen3 instance with `format: "json"` set but `think` left on). The
analyzer explicitly sends `"think": false` to avoid this, which also
roughly halved response latency in testing. If you ever swap in a
different reasoning model, double-check it still respects that flag.
