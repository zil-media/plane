#!/usr/bin/env bash
# Shared helpers for the agent-lane scripts. Sourced, never executed.
#
# Nothing here interpolates agent-authored text (file names, commit messages) into another
# command: the chain starts at a bug report any authenticated Ops user can write.

UUID_RE='[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
BASE="${LANE_BASE:-origin/preview}"

emit() { [ -n "${GITHUB_OUTPUT:-}" ] && echo "$1" >> "$GITHUB_OUTPUT"; return 0; }
summary() { [ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo "$1" >> "$GITHUB_STEP_SUMMARY"; return 0; }

fetch_base() {
    [ "$BASE" = "origin/preview" ] && git fetch origin preview
    return 0
}

# Values of one trailer key on one commit, one per line. Uses git's trailer parser, not a grep over
# the body: git only reads trailers from the LAST paragraph, so a Bug-Id quoted in prose (or pasted
# from a bug report) never counts.
trailer_values() {
    local key="$1" sha="$2"
    git log -1 --format="%(trailers:key=${key},valueonly,separator=%x0A)" "$sha" \
        | sed 's/[[:space:]]*$//' | grep -v '^$' || true
}

# Every well-formed id of `key` in base..tip (lowercased, unique).
trailer_ids() {
    local key="$1" tip="$2" sha value
    for sha in $(git rev-list --no-merges "${BASE}..${tip}"); do
        while IFS= read -r value; do
            [ -n "$value" ] || continue
            value=$(printf '%s' "$value" | tr 'A-F' 'a-f')
            printf '%s' "$value" | grep -qE "^${UUID_RE}$" && echo "$value"
        done <<< "$(trailer_values "$key" "$sha")"
    done | sort -u
}
