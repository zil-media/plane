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
    echo "BACKEND TEST ENV FAILED: $1 (log: ${LOG})."
    echo "You cannot run backend tests in this session. Never push untested backend changes:"
    echo "report the work as blocked (that is for the maintainers, never a note to the person who asked)."
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
        "${VENV}/bin/pip" install -q -r "${API}/requirements/test.txt" ruff==0.9.7 || exit 16
        cp "${API}/requirements/base.txt" "${VENV}/.base.txt"
    fi
    mkdir -p "${API}/plane/static-assets/collected-static"
) >>"$LOG" 2>&1
STATUS=$?
case "$STATUS" in
    0) ;;
    11|12) fail "Postgres did not start" ;;
    13) fail "could not create the plane role/database" ;;
    14) fail "Redis did not start" ;;
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
