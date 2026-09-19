#!/usr/bin/env bash
# How far into agent-batch can this window ship? Outputs: ship_sha, partial, blocked_sha, blocked_files.
#
# Normally the whole batch. If the combined batch touches a denylisted file (a feature merged
# from a reviewed PR can't, but a manual push to agent-batch could), everything BEFORE the first
# commit that touches it still ships, and the rest waits for a person instead of freezing every fix.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TIP="${LANE_TIP:-origin/agent-batch}"
REPORT="${GUARD_REPORT:-/tmp/guard-report.md}"
GUARD_BIN=/tmp/check-agent-diff.preview.mjs

if ! git show "${BASE}:.github/ci/check-agent-diff.mjs" > "$GUARD_BIN" 2>/dev/null; then
    echo "::error::Could not read the guard from ${BASE}. Without it this window gates nothing."
    exit 1
fi

guard_clean() {
    git checkout --quiet --detach "$1"
    node "$GUARD_BIN" --base "$BASE" --strict --report "$2" >/dev/null 2>&1
}

TIP_SHA=$(git rev-parse "$TIP")
if guard_clean "$TIP_SHA" "$REPORT"; then
    emit "ship_sha=${TIP_SHA}"
    emit "partial=false"
    echo "Guard clean on the whole batch: shipping ${TIP_SHA}"
    exit 0
fi

FILES=$(awk '/⛔/ { inside = 1; next } inside && /^### / { exit } inside' "$REPORT" \
    | grep -oE '^\| `[^`]+`' | sed 's/^| `//; s/`$//' || true)
if [ -z "$FILES" ]; then
    echo "::error::The guard cut for something that is not a denylisted file (deletions under --strict?). The batch is not split: read the report."
    cat "$REPORT" >> "${GITHUB_STEP_SUMMARY:-/dev/null}" 2>/dev/null || true
    exit 1
fi

ORDER=$(git rev-list --reverse "${BASE}..${TIP_SHA}")
FIRST_BAD=""
FIRST_IDX=""
while IFS= read -r f; do
    [ -n "$f" ] || continue
    c=$(git rev-list --reverse "${BASE}..${TIP_SHA}" -- "$f" | head -1)
    [ -n "$c" ] || continue
    idx=$(printf '%s\n' "$ORDER" | grep -n "^${c}$" | cut -d: -f1 | head -1)
    [ -n "$idx" ] || continue
    if [ -z "$FIRST_IDX" ] || [ "$idx" -lt "$FIRST_IDX" ]; then
        FIRST_IDX="$idx"
        FIRST_BAD="$c"
    fi
done <<< "$FILES"

if [ -z "$FIRST_BAD" ]; then
    echo "::error::The guard flagged denylisted files but no commit in the range touches them. Inconsistent state: check by hand."
    exit 1
fi
emit "blocked_sha=${FIRST_BAD}"
emit "blocked_files=$(echo "$FILES" | tr '\n' ' ')"

CAND="${FIRST_BAD}~1"
SHIP=""
for _ in $(seq 1 10); do
    SHA=$(git rev-parse --verify --quiet "${CAND}^{commit}") || break
    git checkout --quiet -B pick-try "$BASE"
    if git merge --no-edit "$SHA" >/dev/null 2>&1; then
        MERGED=$(git rev-parse HEAD)
        if [ "$(git rev-list --count "${BASE}..${MERGED}")" != "0" ] && guard_clean "$MERGED" /tmp/guard-partial.md; then
            SHIP="$MERGED"
            break
        fi
    else
        git merge --abort 2>/dev/null || true
    fi
    CAND="${SHA}~1"
done

if [ -z "$SHIP" ]; then
    emit "partial=false"
    emit "ship_sha="
    echo "::error::The first commit of the batch (${FIRST_BAD}) touches a denylisted file: nothing ships before it. A person has to merge it."
    exit 1
fi

emit "ship_sha=${SHIP}"
emit "partial=true"
echo "::warning::Shipping up to ${SHIP}; $(git rev-list --count "${SHIP}..${TIP_SHA}") commit(s) stay on agent-batch behind ${FIRST_BAD}."
