#!/usr/bin/env bash
# Merges the pushed commit into `preview` or `agent-batch` and pushes, retrying when the target
# moved underneath (another lane wrote it meanwhile). Outputs: merged=true | conflict=true.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TARGET="${1:?target branch missing}"
HEAD_SHA="${GITHUB_SHA:?GITHUB_SHA missing}"

case "$TARGET" in
    preview|agent-batch) ;;
    *) echo "::error::Unknown target ${TARGET}"; exit 2 ;;
esac

git config user.name "zil-agent-bot"
git config user.email "bot@zil.global"

for attempt in 1 2 3; do
    if ! git fetch origin preview; then
        echo "::warning::fetching preview failed (attempt ${attempt}/3)"
        [ "$attempt" -lt 3 ] && sleep $((attempt * 5))
        continue
    fi
    if [ "$TARGET" = "agent-batch" ]; then
        git fetch origin agent-batch 2>/dev/null || true
        git checkout -B agent-batch origin/agent-batch 2>/dev/null || git checkout -B agent-batch origin/preview
    else
        git checkout -B preview origin/preview
    fi

    if ! git merge --no-edit "$HEAD_SHA"; then
        git merge --abort 2>/dev/null || true
        emit "conflict=true"
        echo "::error::Conflict merging ${GITHUB_REF_NAME:-the branch} into ${TARGET}. Left for a person."
        exit 1
    fi

    if git push origin "$TARGET"; then
        emit "merged=true"
        echo "Merged into ${TARGET}: $(git rev-parse --short HEAD)"
        exit 0
    fi
    echo "::warning::push to ${TARGET} rejected (attempt ${attempt}/3): it moved while this job ran. Redoing the merge on the new tip."
    [ "$attempt" -lt 3 ] && sleep $((attempt * 5))
done

echo "::error::Could not push to ${TARGET} in 3 attempts. ${GITHUB_REF_NAME:-The branch} stays unmerged."
exit 1
