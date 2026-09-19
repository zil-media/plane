#!/usr/bin/env bash
# Runs one CI gate. When it fails, the tail of its output is re-emitted as a
# workflow annotation: this repo's job logs need a signed-in viewer, while
# annotations are readable anonymously (API and run page) — including by the
# agent sessions that have to fix what the gate caught.
#
# Usage: .github/ci/gate.sh "<gate name>" <command> [args...]
set -uo pipefail

name="$1"
shift
log="$(mktemp)"

"$@" 2>&1 | tee "$log"
code=${PIPESTATUS[0]}

if [ "$code" -ne 0 ]; then
  # GitHub caps an annotation at 4096 chars and keeps the head, so send only the
  # tail: that is where summaries (pytest's, tsc's error count) end up.
  body="$(sed -e 's/\x1b\[[0-9;]*[A-Za-z]//g' -e 's/\r//g' "$log" | tail -c 3600 \
    | sed -e 's/%/%25/g' | awk 'BEGIN { ORS = "%0A" } { print }')"
  echo "::error title=${name} failed::${body}"
fi

rm -f "$log"
exit "$code"
