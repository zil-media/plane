#!/usr/bin/env bash
# Is this push the bug fixer's, or any other cloud session?
#
# `claude/**` is the default branch prefix of EVERY Claude Code cloud session: the fixer, a one-off
# routine, and a person working by hand. Only the fixer may merge to production.
#
#   - No commit has a `Bug-Id:` trailer        -> not this lane. eligible=false, exit 0 (grey, no mail).
#   - Some commits have it and some don't      -> the fixer, with a malformed push. exit 1.
#   - A trailer is present but not a UUID      -> the fixer, with an id that is no bug. exit 1.
#   - All well formed                          -> eligible=true.
#
# Keep the next job cut by `needs` + `if`: determine-tier treats "no Bug-Ids" as urgent, so
# relaxing this gate inside a single job would auto-deploy any cloud session.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

HEAD_SHA="${GITHUB_SHA:?GITHUB_SHA missing}"
fetch_base

WELL_FORMED=0
UNTAGGED=""
MALFORMED=""

for SHA in $(git rev-list --no-merges "${BASE}..${HEAD_SHA}"); do
    VALUES=$(trailer_values Bug-Id "$SHA")
    if [ -z "$VALUES" ]; then
        UNTAGGED="${UNTAGGED} $(git log -1 --format='%h %s' "$SHA")"
        continue
    fi
    BAD=$(printf '%s\n' "$VALUES" | grep -ivE "^${UUID_RE}$" || true)
    if [ -n "$BAD" ]; then
        MALFORMED="${MALFORMED} $(git log -1 --format='%h' "$SHA") [$(printf '%s' "$BAD" | tr '\n' ' ')]"
    else
        WELL_FORMED=$((WELL_FORMED + 1))
    fi
done

if [ -n "$MALFORMED" ]; then
    echo "::error::A 'Bug-Id:' trailer is not a UUID, so it identifies no bug:${MALFORMED}"
    echo "::error::Nothing is merged: with an invalid id the bug is never resolved and the reporter never hears back."
    emit "eligible=false"
    exit 1
fi

if [ "$WELL_FORMED" -eq 0 ]; then
    echo "No 'Bug-Id:' trailers in this push: not the bug lane. Nothing is gated or merged."
    summary "## Bug lane: not applicable"
    summary ""
    summary "No commit on \`${GITHUB_REF_NAME:-this branch}\` carries a \`Bug-Id:\` trailer. Expected for a normal cloud session; if this WAS a bug fix, every commit needs \`Bug-Id: <uuid>\`."
    emit "eligible=false"
    exit 0
fi

if [ -n "$UNTAGGED" ]; then
    echo "::error::This push is the fixer's (${WELL_FORMED} commit(s) carry Bug-Id) but these don't:${UNTAGGED}"
    echo "::error::Nothing is merged: an untagged commit would reach production tied to no bug."
    emit "eligible=false"
    exit 1
fi

echo "All ${WELL_FORMED} commit(s) carry a well-formed Bug-Id: bug lane."
emit "eligible=true"
