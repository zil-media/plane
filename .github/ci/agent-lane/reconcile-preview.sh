#!/usr/bin/env bash
# Merges preview into the branch BEFORE gating: the gates must test what will actually be merged,
# not a stale base (a branch cut from a broken preview would otherwise stay red forever).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

git config user.name "zil-agent-bot"
git config user.email "bot@zil.global"
fetch_base

if ! git merge --no-edit "$BASE"; then
    git merge --abort 2>/dev/null || true
    echo "::error::${GITHUB_REF_NAME:-this branch} conflicts with preview. Nothing is gated or merged: resolve the conflict on the branch."
    exit 1
fi

echo "preview reconciled into the branch: $(git rev-parse --short HEAD)"
