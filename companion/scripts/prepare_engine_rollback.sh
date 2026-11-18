#!/bin/sh
# Step 1 of rolling the database engine back (upgrading.md, "Moving the database engine"): while the NEW engine is
# still running, put template1 and postgres back on the old TimescaleDB version, so the old engine can open them.
# The old engine can't open a database whose extension is newer than its libraries ("could not access file
# timescaledb-2.31.0"). Neither database holds data, so the extension is dropped and created again at the old
# version; the new image ships the old version's install script and library. Database healthlog is left alone:
# restore.sh replaces it in step 3.
#
#   companion/scripts/prepare_engine_rollback.sh timescale/timescaledb:2.17.2-pg16
#   then: switch healthlog-db to that image (HEALTHLOG_DB_IMAGE in .env, `up -d healthlog-db`),
#   then: companion/scripts/restore.sh <dump from before the move> --replace-live-data
#
# DB_CONTAINER points it at a rehearsal copy (upgrade_rehearsal.sh does).
set -eu

old_image=${1:?usage: prepare_engine_rollback.sh <old timescaledb image>}
db=${DB_CONTAINER:-healthlog-db}
old=$(docker run --rm --entrypoint sh "$old_image" -c \
    "sed -nE \"s/^default_version *= *'([^']+)'.*/\\1/p\" /usr/local/share/postgresql/extension/timescaledb.control")
[ -n "$old" ] || { echo "can't read the TimescaleDB version of $old_image" >&2; exit 2; }
for d in template1 postgres; do
    docker exec "$db" psql -U healthlog -d "$d" -tAXq -v ON_ERROR_STOP=1 \
        -c "drop extension if exists timescaledb" -c "create extension timescaledb version '$old'"
    echo "$d: timescaledb $(docker exec "$db" psql -U healthlog -d "$d" -tAX \
        -c "select extversion from pg_extension where extname = 'timescaledb'")"
done
