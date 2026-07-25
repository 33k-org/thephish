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

RUN pip install --no-cache-dir -r requirements.txt

# Real config (with secrets) is rendered from these templates at container
# start, from environment variables - see entrypoint.sh/render_config.py.
# Keeps secrets out of the image and out of git, consistent with how every
# other host in this repo handles them (.env, never committed).
COPY config-template /opt/thephish-config-template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
