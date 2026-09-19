#!/usr/bin/env bash
# A stuck pipeline (merge conflict, red preview, split batch) becomes a blocking bug in Ops, which
# fires the fixer routine as urgent: the agent does the git surgery (instructions, section 5b).
#
#   report-incident.sh <kind> <branch> <detail>
set -euo pipefail

KIND="${1:?kind missing}"
BRANCH="${2:?branch missing}"
DETAIL="${3:?detail missing}"
LANE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RUN_URL=""
[ -n "${GITHUB_RUN_ID:-}" ] && RUN_URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"

{
    echo "## Pipeline stuck: ${KIND}"
    echo
    echo "- Branch: \`${BRANCH}\`"
    [ -n "$RUN_URL" ] && echo "- Run: ${RUN_URL}"
    echo
    printf '%s\n' "$DETAIL"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}" 2>/dev/null || true

if [ -z "${AGENT_API_KEY:-}" ] || [ -z "${API_URL:-}" ]; then
    echo "::warning::Agent secrets missing: the incident was NOT filed. Unstick the pipeline by hand."
    exit 0
fi

PAYLOAD=$(jq -n --arg kind "$KIND" --arg branch "$BRANCH" --arg run_url "$RUN_URL" --arg detail "${DETAIL:0:2000}" \
    '{kind: $kind, branch: $branch, run_url: $run_url, detail: $detail}')

if "$LANE_DIR/agent-api.sh" incident - "$PAYLOAD"; then
    echo "Incident filed: the fixer routine picks it up as blocking."
else
    echo "::error::The incident could NOT be filed. Nobody will pick this up automatically: unstick ${BRANCH} by hand."
fi
