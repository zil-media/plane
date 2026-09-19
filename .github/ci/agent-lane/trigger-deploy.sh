#!/usr/bin/env bash
# Starts build-and-push.yml on preview after a lane merged into it.
#
# Pushes made with GITHUB_TOKEN never trigger other workflows (GitHub's anti-recursion rule), so
# the merge alone would leave production on the old images. workflow_dispatch is the documented
# exception and only needs `actions: write`.
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN missing}"

for attempt in 1 2 3; do
    if gh workflow run build-and-push.yml --ref preview; then
        echo "Deploy started: build-and-push.yml on preview."
        exit 0
    fi
    echo "::warning::could not start build-and-push (attempt ${attempt}/3)"
    [ "$attempt" -lt 3 ] && sleep $((attempt * 5))
done

echo "::error::The fix IS merged into preview but the deploy did not start. Run build-and-push.yml by hand."
exit 1
