#!/bin/sh
set -eu

# ThePhish-NG has no polling loop of its own (see mail-server/README.md's
# "verdict-email flow" section) - something has to call /api/list and then
# /api/analysis for each new email. This is that something: runs as its
# own container (same image, entrypoint overridden - see
# mail-server/docker-compose.yml's "poller" service), calling ThePhish-NG's
# own HTTP API exactly like a human clicking through the UI would.
#
# Sequential by design: waits for each analysis to finish before starting
# the next and before the next /api/list poll, rather than firing them
# concurrently - simpler to reason about, and this is a low-volume triage
# mailbox, not something that needs throughput.

POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-60}"

echo "[poller] starting - polling http://thephish:8080/api/list every ${POLL_INTERVAL_SECONDS}s"

while true; do
	emails="$(curl -sf http://thephish:8080/api/list)" || {
		echo "[poller] /api/list failed, retrying next cycle"
		emails=""
	}

	uids="$(printf '%s' "$emails" | python3 -c "
import json, sys
try:
	data = json.load(sys.stdin)
except Exception:
	data = []
for e in data:
	print(e['mailUID'])
" 2>/dev/null)" || uids=""

	for uid in $uids; do
		sid="auto-$(date +%s)-${uid}"
		echo "[poller] analyzing mailUID=${uid} (sid=${sid})"
		curl -sf -X POST http://thephish:8080/api/analysis \
			-F "mailUID=${uid}" \
			-F "sid=${sid}" \
			--max-time 600 \
			|| echo "[poller] analysis failed or timed out for mailUID=${uid}"
	done

	sleep "$POLL_INTERVAL_SECONDS"
done
