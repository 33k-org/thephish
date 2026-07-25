FROM python:3.12-slim

# ThePhish-NG has no releases/tags and no published Docker image (checked
# 2026-07-22) - pin to a specific commit for a reproducible build instead of
# floating on master. Bump this deliberately when you want to pick up
# upstream changes.
ARG THEPHISH_NG_COMMIT=16c62ceef8ec62729702061edc33f0deb35d83db

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/thephish

RUN curl -fsSL "https://github.com/dead-plant/ThePhish-NG/archive/${THEPHISH_NG_COMMIT}.tar.gz" \
      | tar -xz --strip-components=1

# Upstream only ever auto-triggers Yara_3_0 on the forwarded .eml's file
# observable (app/services/run_analysis.py) - there's no generic "run every
# enabled file-type analyzer" path for it, unlike url/domain/mail/ip/hash
# observables. That silently excludes our own Ollama_Phishing_Analysis_1_0
# analyzer (also a file-type analyzer) from ever running automatically via
# the normal "Analyze" button - confirmed live: case/observable/Mailer all
# worked, but Ollama never got triggered until this patch. Explicitly add
# it alongside Yara rather than opening the check up to every enabled file
# analyzer, since not all file analyzers are meaningful on a raw .eml.
RUN sed -i \
      "s/if analyzer.name == 'Yara_3_0':/if analyzer.name in ('Yara_3_0', 'Ollama_Phishing_Analysis_1_0'):/" \
      app/services/run_analysis.py \
    && grep -q "Ollama_Phishing_Analysis_1_0" app/services/run_analysis.py

# Upstream only auto-resolves the case and auto-sends the verdict email for
# "Malicious"/"Safe" - "Suspicious" is deliberately left open for a human to
# write and send the reply by hand. This deployment wants the whole pipeline
# to run unattended end-to-end regardless of verdict, always replying to the
# sender - see patches/auto_resolve_all_verdicts.py for the exact change.
COPY patches/auto_resolve_all_verdicts.py /tmp/auto_resolve_all_verdicts.py
RUN python3 /tmp/auto_resolve_all_verdicts.py \
    && grep -q "elif verdict == 'Suspicious':" app/services/run_analysis.py

# A forwarded email with no message/rfc822 (.eml) attachment - i.e.
# forwarded inline instead of as an attachment, the default "Forward" in
# most mail clients - is silently dropped by app/services/list_emails.py:
# never listed, never analyzed, no error, just silently re-skipped on
# every future poll forever. Confirmed live. Notify the sender once
# instead, then mark it seen - see patches/notify_wrong_format.py.
COPY patches/notify_wrong_format.py /tmp/notify_wrong_format.py
RUN python3 /tmp/notify_wrong_format.py \
    && grep -q "def notify_wrong_format" app/services/list_emails.py

# Recover a forwarded email from inline-quoted body text (the default
# "Forward" in most mail clients pastes the original as quoted text
# rather than attaching it), instead of just telling the sender to
# resend as an attachment - "cut the last forward and create the eml
# file from the rest". New shared module, plus wiring into both
# list_emails.py (listing) and case_from_email.py (actual analysis) -
# must run after notify_wrong_format.py above (patches
# list_emails.py's same eml_attachment_found check).
COPY patches/inline_forward.py app/utils/inline_forward.py
COPY patches/enable_inline_forward.py /tmp/enable_inline_forward.py
RUN python3 /tmp/enable_inline_forward.py \
    && grep -q "inline_forward.extract" app/services/list_emails.py \
    && grep -q "inline_forward.extract" app/services/case_from_email.py

# Pre-existing bug, confirmed live on completely ordinary forwarded email
# (not anything deliberately malformed): case_from_email.py's parse_eml()
# serializes the parsed message back to bytes via a strict-ASCII
# BytesGenerator policy, which crashes outright on any real Unicode
# character not properly declared/encoded (smart quotes, figure spaces,
# em-dashes - extremely common in real HTML email). Since this happens
# before the case is even created, the sender gets total silence - no
# case, no notification, nothing. See patches/fix_eml_unicode_serialization.py.
COPY patches/fix_eml_unicode_serialization.py /tmp/fix_eml_unicode_serialization.py
RUN python3 /tmp/fix_eml_unicode_serialization.py \
    && grep -q "strbuf.getvalue().encode" app/services/case_from_email.py

# Upstream's verdict-email body is a single bare sentence with no
# reasoning or indication of what was actually flagged. Pull in our own
# Ollama analyzer's reasoning/confidence (already computed, previously
# just discarded) and a list of flagged observables for a more useful
# reply - see patches/detailed_verdict_email.py for the exact change.
COPY patches/detailed_verdict_email.py /tmp/detailed_verdict_email.py
RUN python3 /tmp/detailed_verdict_email.py \
    && grep -q "Automated analysis findings" app/services/run_analysis.py

RUN pip install --no-cache-dir -r requirements.txt

# Real config (with secrets) is rendered from these templates at container
# start, from environment variables - see entrypoint.sh/render_config.py.
# Keeps secrets out of the image and out of git, consistent with how every
# other host in this repo handles them (.env, never committed).
COPY config-template /opt/thephish-config-template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ThePhish-NG has no polling loop of its own - poller.sh calls its own
# /api/list + /api/analysis HTTP API on a timer, same as a human clicking
# through the UI. Runs as a separate container using this same image with
# its entrypoint overridden - see docker-compose.yml's "poller" service.
COPY poller.sh /poller.sh
RUN chmod +x /poller.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
