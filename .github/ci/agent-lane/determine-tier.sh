#!/usr/bin/env bash
# urgent (merge to preview now, deploy) vs batch (accumulate on agent-batch for the next window).
# Outputs: tier, bug_ids.
#
# A bug is urgent when its reporter marked it blocking or its computed urgency is `urgent`.
# A bug id that 404s fails the run: the trailer points at nothing. An unreachable API defaults to
# urgent — the fix already passed every gate, and silence is worse than an early deploy.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

HEAD_SHA="${GITHUB_SHA:?GITHUB_SHA missing}"
fetch_base

BUG_IDS=$(trailer_ids Bug-Id "$HEAD_SHA")

DELIM="BUGIDS_$(date +%s)_${RANDOM}_${RANDOM}"
{
    echo "bug_ids<<${DELIM}"
    echo "$BUG_IDS"
    echo "${DELIM}"
} >> "${GITHUB_OUTPUT:-/dev/null}"

TIER=batch
[ -n "$BUG_IDS" ] || TIER=urgent

for BUG_ID in $BUG_IDS; do
    : > /tmp/bug.json
    HTTP=$(curl -s -o /tmp/bug.json -w '%{http_code}' --connect-timeout 10 --max-time 30 \
        -H "Authorization: Bearer ${AGENT_API_KEY:-}" \
        "${API_URL:-}/api/agent/bugs/${BUG_ID}/" || true)
    case "$HTTP" in ''|*[!0-9]*) HTTP=000 ;; esac

    if [ "$HTTP" = "404" ]; then
        echo "::error::The trailer points at bug ${BUG_ID}, which does not exist. Nothing is merged."
        exit 1
    fi
    if [ "$HTTP" != "200" ] || ! jq -e . /tmp/bug.json >/dev/null 2>&1; then
        echo "::warning::Could not read bug ${BUG_ID} (HTTP ${HTTP}): tier=urgent to be safe"
        TIER=urgent
        break
    fi

    SEV=$(jq -r '.severity // ""' /tmp/bug.json)
    URG=$(jq -r '.urgency // ""' /tmp/bug.json)
    echo "Bug ${BUG_ID}: severity='${SEV}' urgency='${URG}'"
    if [ "$SEV" = "bloqueante" ] || [ "$URG" = "urgent" ]; then
        TIER=urgent
    fi
done

emit "tier=${TIER}"
echo "Deploy tier: ${TIER}"
