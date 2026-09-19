#!/usr/bin/env bash
# Runs one CI gate. When it fails, the tail of its output is re-emitted as a
# workflow annotation: this repo's job logs need a signed-in viewer, while
# annotations are readable anonymously (API and run page) — including by the
# agent sessions that have to fix what the gate caught.
#
# Usage: scripts/ci/gate.sh "<gate name>" <command> [args...]
set -uo pipefail

name="$1"
shift
log="$(mktemp)"

"$@" 2>&1 | tee "$log"
code=${PIPESTATUS[0]}

if [ "$code" -ne 0 ]; then
  body="$(tail -n 80 "$log" \
    | sed -e 's/\x1b\[[0-9;]*[A-Za-z]//g' -e 's/%/%25/g' -e 's/\r//g' \
    | awk 'BEGIN { ORS = "%0A" } { print }')"
  echo "::error title=${name} failed::${body}"
fi

rm -f "$log"
exit "$code"
