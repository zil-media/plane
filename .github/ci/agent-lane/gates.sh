#!/usr/bin/env bash
# The same bar as preview-ci.yml, run on the reconciled tree of an agent branch or batch.
#
#   gates.sh backend    ruff, makemigrations --check, pytest (docker-compose-test.yml)
#   gates.sh frontend   format, lint, types, build
#
# Every gate runs even if an earlier one failed, so one run reports all problems (and each failure
# is surfaced as an annotation by gate.sh). Expects the setup steps of the calling workflow: python
# with ruff, the plane-api-tests image built, pnpm + node.
set -uo pipefail

CI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATE="${CI_DIR}/gate.sh"
FAILED=""

run() {
    local name="$1"
    shift
    bash "$GATE" "$name" "$@" || FAILED="${FAILED} ${name}"
}

case "${1:?backend|frontend}" in
    backend)
        cp apps/api/.env.example apps/api/.env
        echo "SECRET_KEY=\"ci-$(openssl rand -hex 24)\"" >> apps/api/.env
        run ruff ruff check apps/api
        run makemigrations docker compose -f docker-compose-test.yml run --rm api-tests \
            python manage.py makemigrations --check --dry-run
        run pytest docker compose -f docker-compose-test.yml run --rm api-tests \
            pytest -p no:cacheprovider -o addopts="--strict-markers --reuse-db --nomigrations" -q -rfE --disable-warnings
        docker compose -f docker-compose-test.yml down -v >/dev/null 2>&1 || true
        ;;
    frontend)
        if ! pnpm install --frozen-lockfile; then
            echo "::error::pnpm install --frozen-lockfile failed"
            exit 1
        fi
        run format pnpm check:format
        run lint pnpm check:lint
        run types pnpm check:types
        run build pnpm build
        ;;
    *)
        echo "::error::unknown gate group: $1"
        exit 2
        ;;
esac

if [ -n "$FAILED" ]; then
    echo "::error::Failed gates:${FAILED}"
    exit 1
fi
echo "All $1 gates passed."
