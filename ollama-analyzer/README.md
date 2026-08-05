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
  for a JSON verdict (`malicious`/`suspicious`/`spam`/`safe` + confidence +
  reasons - see "Verdict categories" below for why there are 4, not 3),
  and reports it with a matching Cortex taxonomy level.
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

## Verdict categories: `spam` as its own thing, not lumped into `safe`

The original 3-category prompt (`malicious`/`suspicious`/`safe`) defined
"safe" broadly enough to include ordinary bulk marketing/newsletters -
useful for *not* flagging them as a threat, but it meant a genuine cold
sales email and a real colleague's reply looked identical in the
verdict. `safe` and `spam` are now separate: `spam` is unsolicited bulk/
commercial mail with no phishing indicators (not a security threat, just
unwanted), `safe` is genuine wanted correspondence or an expected service
notification. Neither is malicious or suspicious - the split is purely
about signal quality for the recipient, not risk.

Cortex's own taxonomy only has 4 fixed levels
(`info`/`safe`/`suspicious`/`malicious` - `cortexutils`' `build_taxonomy()`
silently forces anything else to `info`), so there's no native `spam`
level to use there. `spam` maps to the `safe` level for Cortex/TheHive's
own coloring (it's not a threat), but the literal `spam` string is still
passed as the taxonomy's displayed value, and separately threaded through
`mail-server/thephish/patches/spam_category.py` (applied to
`run_analysis.py` at Docker build time) so the case-level verdict itself -
and the reply the sender actually receives - says "Spam", not "Safe".
Confirmed live: a cold-outreach marketing test email came back
`verdict: "Spam"`, case resolved as `FalsePositive`, and the reply
correctly read "...has been classified as Spam" with the model's actual
reasoning (unsolicited commercial marketing, no phishing indicators, no
urgency, no credential/data request, no domain impersonation).

## A more elaborate checklist, to stop over-using `suspicious`

The original "before deciding, check" list was 4 short items - real-world
testing showed the model treating `suspicious` as a safe default whenever
it wasn't fully confident, even for completely ordinary brand
notifications with no actual red flag. Expanded to 9 specific, concrete
checks (domain/URL legitimacy, credential/payment requests, urgency/fear
tactics, From/Reply-To/link mismatches, bypass-normal-channels requests,
attachment risk, generic-greeting-vs-claimed-relationship, authority
impersonation, and grammar as an explicitly weak-only signal), with
explicit instructions that `suspicious` is for a *specific* checklist
item that's genuinely ambiguous after actually being checked - not a
hedge for general unfamiliarity - and that clean checklist results should
resolve to `spam` or `safe`, never `suspicious`.

Re-tested against the same 6 real emails used for the model comparison
above, plus the cold-outreach spam sample: 5/6 resolved decisively and
correctly (2 Malicious, 3 Safe), each citing specific checklist item
numbers rather than vague reasoning; the spam sample still correctly came
back `spam` (90% confidence, no regression from the added rigor); the one
remaining `suspicious` case cited a concrete signal (a From-header/body
address mismatch) rather than general uncertainty. Reasoning quality also
improved on cases that look ambiguous at first glance but aren't - one
case's model output correctly reasoned that a From-header oddity was "due
to forwarding, not spoofing," rather than treating it as a red flag.

### Follow-up false positive: ESP tracking domains aren't lookalikes

A real submission (a Swedish birthday-reminder service, "Birthday.se")
still came back `suspicious` - checklist item (1) treated its
click-tracking links (on `awstrack.me`, Amazon SES's standard tracking/
redirect domain) as "not the expected brand domain, raising uncertainty."
That's wrong: routing links through a completely unrelated third-party
domain is the *normal* way bulk/transactional email works (Amazon SES,
SendGrid, Mailchimp, Constant Contact, etc. all do this) - it's a
different thing entirely from a domain that's actually trying to *look
like* the brand's own name (the real red flag item (1) is meant to
catch). Considered having the model do a live web search to verify
domains instead, but rejected it - it would mean sending email content to
an external search API on every analysis, undermining the whole point of
running this locally, for a problem that's really just under-specified
prompting, not missing information.

Rewrote item (1) to explicitly separate the two cases, with named
examples of common legitimate ESP tracking domains (`awstrack.me`,
`sendgrid.net`, `mandrillapp.com`, `list-manage.com`, `constantcontact.com`,
`click.e.*`). Confirmed on the real email that triggered this: verdict
changed from `suspicious` to `spam` (90% confidence), citing "all links
use legitimate third-party tracking domains... no brand-impersonating
domain." Re-ran the full 6-email set from above too - no regressions,
all resolved decisively.
