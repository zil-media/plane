#!/usr/bin/env bash
# SessionStart, cloud sessions only (the bug fixer, feature agent and PR manager routines run there).
#
# The routines have no Docker, so docker-compose-test.yml can't run and they pushed backend code
# without running a single test ("couldn't run the server tests in this environment"). The cloud
# image ships Postgres and Redis: this starts them, installs the test requirements and exports the
# env plane.settings.test reads, so `pytest` works from apps/api like it does in CI.
# CI (gates.sh backend, Docker) stays the gate; this lets the session pass it before pushing.
set -uo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
API="${ROOT}/apps/api"
VENV="${HOME}/.venvs/plane-api"
LOG=/tmp/backend-test-env.log
: > "$LOG"

as_root() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo -n "$@"; fi; }
as_postgres() { if [ "$(id -u)" = 0 ]; then su postgres -c "$1"; else sudo -n -u postgres sh -c "$1"; fi; }
fail() {
    # Never a reason to stop: the lane runs the whole backend suite in Docker (gates.sh backend)
    # before anything merges, so CI is the gate. A session that stopped here left the bug claimed
    # and the reporter waiting on a person (2026-11-09).
    echo "BACKEND TEST ENV FAILED: $1 (log: ${LOG})."
    echo "Backend tests can't run locally in this session. Do NOT stop, do not report blocked:"
    echo "finish the fix, run ruff check apps/api, push, and let CI run the full pytest suite"
    echo "(it gates every merge). Watch that run; if pytest is red, fix it and push again."
    exit 0
}

(
    # Postgres: the image's cluster, or a fresh one when there is none.
    if ! pg_isready -q -h localhost 2>/dev/null; then
        as_root service postgresql start || {
            PGBIN=$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)
            [ -n "$PGBIN" ] || exit 11
            as_root mkdir -p /tmp/pgdata && as_root chown postgres /tmp/pgdata
            as_postgres "$PGBIN/initdb -D /tmp/pgdata -A trust" &&
                as_postgres "$PGBIN/pg_ctl -D /tmp/pgdata -l /tmp/pgdata/log -w start"
        }
    fi
    for _ in $(seq 1 20); do pg_isready -q -h localhost && break; sleep 1; done
    pg_isready -q -h localhost || exit 12
    as_postgres "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='plane'\" | grep -q 1 ||
        psql -c \"CREATE ROLE plane LOGIN SUPERUSER PASSWORD 'plane'\"" || exit 13
    as_postgres "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='plane'\" | grep -q 1 ||
        createdb -O plane plane" || exit 13

    # Redis (Valkey in CI): same protocol.
    redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes >/dev/null || exit 14

    # Test requirements in their own venv; cached for the next session on the same machine.
    if [ ! -x "${VENV}/bin/pytest" ] || ! cmp -s "${API}/requirements/base.txt" "${VENV}/.base.txt"; then
        python3 -m venv "$VENV" || exit 15
        # psycopg-c compiles from source and needs pg_config/libpq headers, which the cloud image
        # lacks: its wheel build failed and every session ended without tests (2026-11-09).
        # psycopg-binary (also in base.txt) ships the same C implementation prebuilt.
        REQS=/tmp/plane-api-reqs
        rm -rf "$REQS" && mkdir -p "$REQS" || exit 16
        grep -viE '^psycopg-c([=<>~ ]|$)' "${API}/requirements/base.txt" > "${REQS}/base.txt"
        cp "${API}/requirements/test.txt" "${REQS}/test.txt"
        # Twice: a single flaky download must not cost the session its tests.
        PIP=("${VENV}/bin/pip" install -q --retries 5 --timeout 60 -r "${REQS}/test.txt" ruff==0.9.7)
        "${PIP[@]}" || "${PIP[@]}" || exit 16
        cp "${API}/requirements/base.txt" "${VENV}/.base.txt"
    fi
    mkdir -p "${API}/plane/static-assets/collected-static"

    # Proves the pieces work together (driver + DB + Django settings), not just that they installed.
    cd "$API" && DJANGO_SETTINGS_MODULE=plane.settings.test \
        DATABASE_URL=postgresql://plane:plane@localhost:5432/plane \
        "${VENV}/bin/python" -c "import psycopg; psycopg.connect('postgresql://plane:plane@localhost:5432/plane').close(); import django" ||
        exit 17
) >>"$LOG" 2>&1
STATUS=$?
case "$STATUS" in
    0) ;;
    11|12) fail "Postgres did not start" ;;
    13) fail "could not create the plane role/database" ;;
    14) fail "Redis did not start" ;;
    17) fail "the installed driver could not reach Postgres" ;;
    *) fail "installing the test requirements failed" ;;
esac

# What docker-compose-test.yml gives the api-tests container: apps/api/.env.example (the .env that
# setup.sh copies), then the service hosts pointed at localhost. No RabbitMQ in the image: Celery
# publishes to kombu's in-process broker, which is all the suite needs (tasks are never consumed).
ENV_LINES=$(
    (
        set -a
        . "${API}/.env.example" >/dev/null 2>&1
        for KEY in $(sed -nE 's/^([A-Z_][A-Z0-9_]*)=.*/\1/p' "${API}/.env.example"); do
            printf 'export %s=%q\n' "$KEY" "${!KEY}"
        done
    )
    cat <<ENVS
export PATH="${VENV}/bin:\$PATH"
export DJANGO_SETTINGS_MODULE=plane.settings.test
export POSTGRES_HOST=localhost
export DATABASE_URL=postgresql://plane:plane@localhost:5432/plane
export REDIS_HOST=localhost REDIS_URL=redis://localhost:6379/
export RABBITMQ_HOST=localhost AMQP_URL=memory://
export EMAIL_HOST=test-smtp.invalid
ENVS
)
[ -n "${CLAUDE_ENV_FILE:-}" ] && printf '%s\n' "$ENV_LINES" >> "$CLAUDE_ENV_FILE"
printf '%s\n' "$ENV_LINES" > /tmp/backend-test-env.sh

echo "Backend tests are runnable here (Postgres + Redis up, test requirements installed)."
echo "Run them from apps/api before every push that touches apps/api:"
echo "  cd apps/api && pytest -p no:cacheprovider -q <the test files you wrote or touched>"
echo "  cd apps/api && pytest -p no:cacheprovider -q            # the whole suite, as CI runs it"
echo "A failing test means you are not done. If a shell lost the env: source /tmp/backend-test-env.sh"
