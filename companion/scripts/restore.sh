#!/bin/sh
# Put the live database back to a backup. This replaces ALL live data (HealthLog and the Companion), so it
# needs the explicit flag. The same restore steps run in every upgrade_rehearsal.sh, so they are tested.
#
#   companion/scripts/restore.sh /mnt/backup/healthlog/db/healthlog-<ts>.dump --replace-live-data
#
# Afterwards, set HEALTHLOG_VERSION in .env back to the version that wrote the backup, then
#   docker compose -f docker-compose.yml -f compose.local.yml -f compose.companion.yml up -d
set -eu

dump=${1:?usage: restore.sh <dump> --replace-live-data}
[ "${2:-}" = "--replace-live-data" ] || { echo "refusing: add --replace-live-data to replace all live data" >&2; exit 2; }
[ -s "$dump" ] || { echo "no such dump: $dump" >&2; exit 2; }
repo=$(cd "$(dirname "$0")/../.." && pwd)
roles=$(dirname "$dump")/roles-$(basename "$dump" .dump | sed 's/^healthlog-//').sql
db=${DB_CONTAINER:-healthlog-db}  # DB_CONTAINER + NO_STOP=1 test this against a rehearsal copy
compose() { docker compose -f "$repo/docker-compose.yml" -f "$repo/compose.local.yml" -f "$repo/compose.companion.yml" "$@"; }

docker exec -i "$db" pg_restore --list < "$dump" > /dev/null  # readable before anything is dropped
if [ "${NO_STOP:-}" != 1 ]; then
    echo "== stopping everything that uses the database"
    compose stop companion-jobs companion-web healthlog grafana
fi
echo "== replacing database healthlog from $(basename "$dump")"
docker exec "$db" psql -U healthlog -d postgres -q -c "drop database healthlog with (force)" -c "create database healthlog"
if [ -s "$roles" ]; then
    docker exec -i "$db" psql -U healthlog -d postgres -q < "$roles" 2>&1 | grep -v "already exists" || true
fi
docker exec "$db" psql -U healthlog -d healthlog -tAX -c "create extension if not exists timescaledb" \
    -c "select timescaledb_pre_restore()" > /dev/null
docker exec -i "$db" pg_restore -U healthlog -d healthlog < "$dump" 2>&1 \
    | grep -Ev 'circular foreign-key|^pg_restore: (detail|hint)|already exists' || true
docker exec "$db" psql -U healthlog -d healthlog -tAX -c "select timescaledb_post_restore()" > /dev/null
echo "schema: $(docker exec "$db" psql -U healthlog -d healthlog -tAX -c 'select version_num from alembic_version')"
echo "== restored. Now set HEALTHLOG_VERSION in .env to the version that wrote this backup, then start the stack."
