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
