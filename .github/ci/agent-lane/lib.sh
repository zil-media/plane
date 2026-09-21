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

# The trailer block of one commit: the run of trailer-only paragraphs at the END of the message.
#
# Not git's own parser, which reads only the LAST paragraph: Claude Code's cloud sessions append
# their own `Co-Authored-By:` and `Claude-Session:` paragraphs after the agent's message, so the
# agent's Feature-Id/Bug-Id ended up one paragraph too early and git never saw it. What must not
# change is why git's rule was chosen: a paragraph with any non-trailer line (prose, a pasted bug
# report) stops the walk, so an id quoted in the body still never counts. The subject line never
# counts either, even when it looks like `fix: x`.
trailer_block() {
    local sha="$1"
    git log -1 --format=%B "$sha" | awk '
        { line[NR] = $0 }
        function blank(i) { return line[i] ~ /^[[:space:]]*$/ }
        END {
            last = NR
            while (last > 0 && blank(last)) last--
            first = last + 1
            end = last
            while (end > 0) {
                start = end
                while (start > 1 && !blank(start - 1)) start--
                if (start == 1) break
                for (k = start; k <= end; k++) if (line[k] !~ /^[A-Za-z0-9-]+:[[:space:]]/) break
                if (k <= end) break
                first = start
                end = start - 1
                while (end > 0 && blank(end)) end--
            }
            for (k = first; k <= last; k++) if (!blank(k)) print line[k]
        }'
}

# Values of one trailer key on one commit, one per line (keys compare case-insensitively, like git).
trailer_values() {
    local key="$1" sha="$2"
    trailer_block "$sha" | awk -v key="$key" '
        { i = index($0, ":") }
        i > 1 && tolower(substr($0, 1, i - 1)) == tolower(key) {
            value = substr($0, i + 1)
            sub(/^[[:space:]]+/, "", value)
            sub(/[[:space:]]+$/, "", value)
            if (value != "") print value
        }' || true
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
