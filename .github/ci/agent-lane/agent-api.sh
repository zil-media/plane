#!/usr/bin/env bash
# Every call the lanes make to the Ops agent API, with one retry policy.
#
#   agent-api.sh <action> <id|-> <json-payload>
#
# Bug actions use AGENT_API_KEY, feature actions FEATURE_AGENT_API_KEY. 5xx/network errors are
# retried; anything else (400, 404, 409) is a real state mismatch and is not.
# The payload is always built with `jq --arg` by the caller: it can carry agent-authored text.
set -euo pipefail

ACTION="${1:?action missing}"
ID="${2:?id missing (or '-')}"
PAYLOAD="${3:?payload missing}"
: "${API_URL:?}"

case "$ACTION" in
    resolve|mark-fixed|blocked|progress)
        METHOD=PUT;  PATH_="/api/agent/bugs/${ID}/${ACTION}/"; KEY="${AGENT_API_KEY:?}" ;;
    incident)
        METHOD=POST; PATH_="/api/agent/bugs/pipeline-incident/"; KEY="${AGENT_API_KEY:?}" ;;
    build-status|merged)
        METHOD=PUT;  PATH_="/api/agent/features/${ID}/${ACTION}/"; KEY="${FEATURE_AGENT_API_KEY:?}" ;;
    *) echo "::error::unknown action: ${ACTION}"; exit 2 ;;
esac

BODY=/tmp/agent-api-resp.json
for attempt in 1 2 3 4 5; do
    : > "$BODY"
    HTTP=$(curl -s -o "$BODY" -w '%{http_code}' --connect-timeout 10 --max-time 30 -X "$METHOD" \
        -H "Authorization: Bearer ${KEY}" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" \
        "${API_URL}${PATH_}" || true)
    case "$HTTP" in ''|*[!0-9]*) HTTP=000 ;; esac

    if [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ]; then
        echo "${ACTION} ${ID}: ${HTTP}"
        exit 0
    fi
    head -c 500 "$BODY" 2>/dev/null || true
    echo
    case "$HTTP" in
        5*|000)
            echo "::warning::${ACTION} ${ID} returned ${HTTP} (attempt ${attempt}/5)"
            [ "$attempt" -lt 5 ] && sleep $((attempt * 5))
            ;;
        *)
            echo "::warning::${ACTION} ${ID} returned ${HTTP}: not retried"
            exit 1
            ;;
    esac
done
exit 1
