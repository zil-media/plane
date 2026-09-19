#!/usr/bin/env bash
# Blast-radius guard with its two step outputs (denied, reason).
#
# Runs PREVIEW's guard, read with `git show` and executed from /tmp: a branch that edits
# check-agent-diff.mjs must not run its own version of the control meant to stop it.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

REPORT="${GUARD_REPORT:-/tmp/guard-report.md}"
fetch_base

GUARD_BIN=/tmp/check-agent-diff.preview.mjs
# An unreadable guard must never degrade to "no guard": the bug lane merges without review.
if ! git show "${BASE}:.github/ci/check-agent-diff.mjs" > "$GUARD_BIN" 2>/dev/null; then
    echo "::error::Could not read .github/ci/check-agent-diff.mjs from ${BASE}. Without the guard this lane gates nothing, so it stops here."
    exit 1
fi

# --strict where nobody reads the report (the lanes that merge on their own): warnings that relied
# on a human, like deleted files, must cut. The feature PR lane runs without it (GUARD_STRICT=0).
STRICT_FLAG=--strict
[ "${GUARD_STRICT:-1}" = "0" ] && STRICT_FLAG=""
set +e
node "$GUARD_BIN" --base "$BASE" ${STRICT_FLAG} --report "$REPORT"
RC=$?
set -e

# A guard cut is not like a failing test: the denylist reserves those files for a person, so a
# retry is guaranteed to hit the same wall. Flag it so the lane blocks the bug and opens a PR.
if [ "$RC" != "0" ]; then
    emit "denied=true"
    # Unique delimiter: the content holds FILE NAMES from the agent's diff.
    DELIM="GUARD_$(date +%s)_${RANDOM}_${RANDOM}"
    {
        echo "reason<<${DELIM}"
        awk '/⛔/ { inside = 1 } inside && /^### / && !/⛔/ { exit } inside' "$REPORT" 2>/dev/null | head -c 900
        echo ""
        echo "${DELIM}"
    } >> "${GITHUB_OUTPUT:-/dev/null}"
fi

cat "$REPORT" >> "${GITHUB_STEP_SUMMARY:-/dev/null}" 2>/dev/null || true
exit $RC
