#!/usr/bin/env bash
# Materializes .github/ci/ FROM PREVIEW and points $LANE at it.
#
# GitHub runs the workflow file of the commit that triggered the push, not preview's, so logic
# living in YAML only applies to branches created after a fix. With the logic in these scripts,
# a fix on preview applies to the next push of every in-flight branch — and the guard that runs
# is preview's, never a copy the agent's branch could have edited.
set -euo pipefail

DEST=/tmp/ci-preview
rm -rf "$DEST"
mkdir -p "$DEST"

git fetch origin preview

if git cat-file -e "origin/preview:.github/ci/agent-lane/lane-check.sh" 2>/dev/null; then
    git archive origin/preview .github/ci | tar -x -C "$DEST"
    echo "CI scripts taken from origin/preview ($(git rev-parse --short origin/preview))"
else
    # Only on the push that introduces this folder, before it reaches preview.
    echo "::warning::preview has no .github/ci/agent-lane yet: using the branch copy."
    mkdir -p "$DEST/.github"
    cp -R .github/ci "$DEST/.github/"
fi

chmod +x "$DEST"/.github/ci/*.sh "$DEST"/.github/ci/agent-lane/*.sh
echo "LANE=${DEST}/.github/ci/agent-lane" >> "$GITHUB_ENV"
echo "CI_DIR=${DEST}/.github/ci" >> "$GITHUB_ENV"
