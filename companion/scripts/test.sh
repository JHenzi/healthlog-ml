#!/bin/sh
# Lint + tests for the Companion, with nothing installed on the host but Docker.
#
#   companion/scripts/test.sh                      # ruff + the whole suite (stats at 20 seeds)
#   companion/scripts/test.sh tests/unit -x        # extra args go to pytest
#   STATS_SEEDS=200 companion/scripts/test.sh tests/stats
#
# Starts (or reuses) a throwaway TimescaleDB, `healthlog-testdb` on 127.0.0.1:55432. Never point the
# suite at the live database: it resets schemas (conftest.py refuses database names not ending in _test).
set -eu

repo=$(cd "$(dirname "$0")/../.." && pwd)
db=healthlog-testdb
image=timescale/timescaledb:2.17.2-pg16

if ! docker ps --format '{{.Names}}' | grep -qx "$db"; then
    if docker ps -a --format '{{.Names}}' | grep -qx "$db"; then
        docker start "$db" >/dev/null
    else
        docker run -d --name "$db" -p 127.0.0.1:55432:5432 \
            -e POSTGRES_USER=healthlog -e POSTGRES_PASSWORD=healthlog -e POSTGRES_DB=healthlog "$image" >/dev/null
    fi
    until docker exec "$db" pg_isready -U healthlog >/dev/null 2>&1; do sleep 1; done
fi

docker run --rm --network host \
    -v "$repo:/repo" -v healthlog-testpip314:/root/.cache/pip -w /repo/companion \
    -e COMPANION_TEST_ADMIN_URL=postgresql+psycopg://healthlog:healthlog@127.0.0.1:55432/companion_test \
    -e STATS_SEEDS="${STATS_SEEDS:-20}" \
    python:3.14-slim sh -c '
        pip install -q --root-user-action=ignore -r requirements-dev.txt >/dev/null 2>&1
        ruff check . && ruff format --check . && python -m pytest -q -W ignore "$@"
    ' sh "$@"
