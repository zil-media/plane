#!/usr/bin/env bash
# When the guard cuts a fix, leave the branch in a PR instead of burying it: the fix is written and
# tested, it just touches a file the denylist reserves for a person.
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN missing}"
BRANCH="${GITHUB_REF_NAME:?GITHUB_REF_NAME missing}"
RUN_URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
REASON="${GUARD_REASON:-}"
[ -n "$REASON" ] || REASON="The blast-radius guard cut this attempt (denylist or deleted files). Details are in the run summary."

EXISTING=$(gh pr list --head "$BRANCH" --state open --json number --jq '.[0].number // empty' 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
    echo "PR #${EXISTING} is already open for ${BRANCH}."
    exit 0
fi

BODY_FILE=/tmp/guard-pr-body.md
{
    echo "The automatic lane **did not merge** this branch: the blast-radius guard cut it."
    echo
    echo "The fix is written and passed the agent's own checks. A person has to review the file the"
    echo "denylist reserves for people. **Do not remove the file from the list to make it pass**: if"
    echo "the change is needed, it goes in reviewed, here."
    echo
    echo "### Why it was cut"
    echo
    printf '%s\n' "$REASON"
    echo
    echo "- Branch: \`${BRANCH}\`"
    echo "- Run: ${RUN_URL}"
} > "$BODY_FILE"

if gh pr create --base preview --head "$BRANCH" \
        --title "[guard] ${BRANCH}: the fix needs a person to touch a protected file" \
        --body-file "$BODY_FILE"; then
    echo "PR opened for ${BRANCH}."
else
    echo "::warning::Could not open the PR for ${BRANCH}. The bug stays blocked; find the branch by hand."
fi
