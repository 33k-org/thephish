# ollama-analyzer

A custom Cortex analyzer that sends a submitted `.eml` file's headers and
body to the GPU box's Ollama instance (`gpt-oss:latest`, the 20B variant
sized for a single GPU - see "Model choice" below for why this replaced
Qwen3) and asks for a phishing/social-engineering verdict, as a signal
alongside app02's stock threat-intel analyzers (VirusTotal, AbuseIPDB,
URLhaus, urlscan.io) - though as of this writing none of those are
actually enabled for this org (see `app02/.env`'s API keys), so in
practice this analyzer is the only signal driving verdicts.

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
- The full path, for real: enabled in Cortex on the real app02 host,
  pointed at the real GPU box (`qwen3:14b`), and run against a real
  submitted email - came back with a correct, well-reasoned verdict. This
  also flushed out two unrelated Cortex-side bugs along the way (both now
  fixed, see `app02/README.md`): the `cortex/jobs` bind mount getting
  auto-created as root, and `--no-config` silently discarding
  `--job-directory`/`--docker-job-directory`.

## A real gotcha found while building this: reasoning models "think" by default

Ollama splits reasoning models' output into a `thinking` field and the
actual message content. Left at its default, both Qwen3 and gpt-oss put
their entire JSON answer inside `thinking`, with the real response coming
back empty - silently breaking this analyzer (confirmed live against
both). The analyzer explicitly sends `"think": false` to avoid this,
which also cuts response latency substantially. If you ever swap in a
different reasoning model, double-check it still respects that flag.

## A real gotcha found while building this: gpt-oss needs `/api/chat`, not `/api/generate`

Qwen3 works fine against Ollama's raw completion endpoint
(`/api/generate`, a single `prompt` string). gpt-oss does not - confirmed
live, it produced garbled, unparseable output through `/api/generate`
(the model appeared confused about its own instructions), while the exact
same prompt through `/api/chat` (a `messages: [{"role": "user", ...}]`
array) worked cleanly for both models. The analyzer uses `/api/chat`
uniformly now.

## Model choice: `gpt-oss:latest` over Qwen3

Real-world testing (see the prompt rewrite this analyzer went through,
`ollama_analyzer.py`'s prompt) surfaced that Qwen3:14b confidently
misclassified multiple legitimate brand notification emails (a Google
OAuth-client notice, a Ubiquiti MFA prompt, a Disney+ login alert) as
Malicious at 90-95% confidence - in one case inventing an incorrect claim
about Ubiquiti's real domain, in another failing to recognize an
ordinary transactional-email subdomain pattern most companies use. No
amount of prompt tuning fixed this reliably; it read as a model
capability/calibration gap, not a prompting gap.

Compared side-by-side against the same real emails:

- **`gpt-oss:120b-cloud`** (via Ollama Cloud - requires the GPU box
  signed into an Ollama account, and sends email content to a third
  party) correctly classified all of the above as Safe with accurate
  domain reasoning, and was equally or more confident on the genuine
  phishing/scam samples in the set.
- **`gpt-oss:latest`** (the 20B variant, runs locally on the GPU box -
  no data leaves this infrastructure) matched `120b-cloud`'s judgment
  almost exactly on the same set - correct on every case `120b-cloud`
  got right except one genuinely ambiguous business email, where it
  landed on Suspicious instead of Safe (a defensible call either way).

Given `gpt-oss:latest` matched the cloud model's quality with no privacy
tradeoff, it replaced Qwen3 as the deployed model. Qwen3:32b (also
available on the GPU box) wasn't tested but remains a reasonable
alternative to try if `gpt-oss:latest`'s judgment degrades on a wider
sample over time.
