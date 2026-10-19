#!/usr/bin/env bash
# Picks the images build-and-push.yml has to build for commit SHA.
#
# The base is the last commit build-and-push published completely (tag ops-deploy/built), not the
# push's `before`: a queued run that replaced a pending one, a failed image or a burst of pushes
# all diff from what is really live, so no change is ever skipped.
#
# An image is built only when its own code changed. In particular the backend (api, worker and
# beat run that one image) is NOT rebuilt for a frontend-only change: a new backend digest makes
# Watchtower recreate the three containers, which drops the API for the length of a boot.
#
# Env: SHA (required), BASE (last published commit, may be empty), ALL=true to build everything.
# Prints the matrix JSON on stdout (`[]` = nothing to build) and the reasoning on stderr.
# Exit 3 = SHA is already published or older than BASE: the run must not deploy anything.
set -euo pipefail

: "${SHA:?SHA missing}"
BASE="${BASE:-}"
ALL="${ALL:-false}"

IMAGES='[
  {"image":"plane-backend","context":"./apps/api","file":"./apps/api/Dockerfile.api","paths":"^apps/api/"},
  {"image":"plane-web","context":".","file":"./apps/web/Dockerfile.web","paths":"^apps/web/"},
  {"image":"plane-space","context":".","file":"./apps/space/Dockerfile.space","paths":"^apps/space/"},
  {"image":"plane-admin","context":".","file":"./apps/admin/Dockerfile.admin","paths":"^apps/admin/"},
  {"image":"plane-live","context":".","file":"./apps/live/Dockerfile.live","paths":"^apps/live/"},
  {"image":"plane-proxy","context":"./apps/proxy","file":"./apps/proxy/Dockerfile.ce","paths":"^apps/proxy/"},
  {"image":"plane-mcp","context":"./apps/mcp","file":"./apps/mcp/Dockerfile","paths":"^apps/mcp/"}
]'
# what every frontend is built from besides its own folder
SHARED='^(packages/|package\.json$|pnpm-lock\.yaml$|pnpm-workspace\.yaml$|turbo\.json$|\.npmrc$)'
FRONTENDS=' plane-web plane-space plane-admin plane-live '
# a change to how images are built rebuilds all of them
BUILD_DEFINITION='^(\.github/workflows/build-and-push\.yml|\.github/ci/build-matrix\.sh)$'

all() { echo "$IMAGES" | jq -c '[.[] | del(.paths)]'; }

if [ "$ALL" = "true" ]; then
  echo "Full rebuild requested." >&2; all; exit 0
fi
if [ -z "$BASE" ] || ! git cat-file -e "${BASE}^{commit}" 2>/dev/null; then
  echo "No published base commit: building everything." >&2; all; exit 0
fi
if git merge-base --is-ancestor "$SHA" "$BASE"; then
  echo "$SHA is already published (base $BASE): nothing to deploy." >&2; exit 3
fi
if ! git merge-base --is-ancestor "$BASE" "$SHA"; then
  echo "Base $BASE is not an ancestor of $SHA (history rewritten): building everything." >&2; all; exit 0
fi

CHANGED=$(git diff --name-only "$BASE" "$SHA")
{ echo "Changed since $BASE:"; echo "$CHANGED"; } >&2
if echo "$CHANGED" | grep -qE "$BUILD_DEFINITION"; then
  echo "The build definition changed: building everything." >&2; all; exit 0
fi

PICKED=""
for row in $(echo "$IMAGES" | jq -c '.[] | {image, paths}'); do
  image=$(echo "$row" | jq -r .image)
  paths=$(echo "$row" | jq -r .paths)
  if echo "$CHANGED" | grep -qE "$paths"; then PICKED="$PICKED $image"; continue; fi
  case "$FRONTENDS" in
    *" $image "*) echo "$CHANGED" | grep -qE "$SHARED" && PICKED="$PICKED $image" ;;
  esac
done
echo "Building:${PICKED:- nothing}" >&2
echo "$IMAGES" | jq -c --arg picked "$PICKED" '[.[] | select(.image as $i | ($picked | split(" ") | index($i))) | del(.paths)]'
