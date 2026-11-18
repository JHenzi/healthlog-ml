#!/bin/sh
# Rehearse a HealthLog upgrade on a copy of the live data. Nothing live is touched.
#
#   companion/scripts/upgrade_rehearsal.sh <healthlog-tag> [dump]     # e.g. v0.6.2, dev
#   KEEP=1 companion/scripts/upgrade_rehearsal.sh dev                  # leave the copy running to look around
#   RUN="rederive-state-of-mind rederive-sleep" companion/scripts/upgrade_rehearsal.sh dev   # post-upgrade steps
#   HEALTHLOG_IMAGE=healthlog-local companion/scripts/upgrade_rehearsal.sh <sha>       # an image built from this checkout
#   DB_IMAGE_TO=timescale/timescaledb:2.31.0-pg16 companion/scripts/upgrade_rehearsal.sh <tag>   # a database engine move
#
# 1. Restores the newest nightly backup (or [dump]) into a throwaway TimescaleDB of the live engine version.
#    That is also the restore test: if this step fails, the backups don't restore.
# 2. Starts the target HealthLog image against the copy; its migrations run on start.
#    RUN lists HealthLog commands to run after the migrations (re-derives a release asks for).
# 3. Runs the Companion's contract check and a full refresh against the migrated copy.
# 4. Prints the schema version and row counts before and after.
#
# With DB_IMAGE_TO (upgrading.md, "Moving the database engine"): a TimescaleDB dump restores only into the
# extension version that wrote it, so step 1 still restores into the live engine. The copy is then restarted on
# DB_IMAGE_TO with the same data, and HealthLog's start updates the extension (app.db_extensions); pgvector is
# updated for the Companion. Row counts must match exactly. Then the rollback is rehearsed too: the copy goes back
# to the live engine and restore.sh puts the dump back, as it would on the live database.
#
# Everything runs on an internal Docker network with no route out, and HealthLog gets a temporary copy of
# config.yaml only (never the live import/ folder). Real data stays on this machine (R4): never run this in CI.
set -eu

target=${1:?usage: upgrade_rehearsal.sh <healthlog-tag> [dump]}
repo=$(cd "$(dirname "$0")/../.." && pwd)
backup_dir=${BACKUP_DIR:-/mnt/backup/healthlog}
dump=${2:-$(ls -1t "$backup_dir"/db/healthlog-*.dump | head -1)}
roles=$(ls -1t "$backup_dir"/db/roles-*.sql | head -1)
db_image=$(docker inspect healthlog-db --format '{{.Config.Image}}')
net=healthlog-rehearsal
db=healthlog-rehearsal-db
volume=healthlog-rehearsal-data
db_image_to=${DB_IMAGE_TO:-}
image=${HEALTHLOG_IMAGE:-ghcr.io/anym001/healthlog}:$target
app=healthlog-rehearsal-app

env_value() { grep -E "^$1=" "$repo/.env" | tail -1 | cut -d= -f2-; }
pg_password=$(env_value POSTGRES_PASSWORD)
companion_password=$(env_value COMPANION_DB_PASSWORD)
tz=$(env_value TZ)
cfg=$(mktemp -d)
cp "$repo/config/config.yaml" "$cfg/"

cleanup() {
    rm -rf "$cfg"
    if [ "${KEEP:-}" = 1 ]; then
        echo "kept: $db and $app on network $net (remove with: docker rm -f $app $db && docker network rm $net)"
        return
    fi
    docker rm -f "$app" "$db" >/dev/null 2>&1 || true
    docker volume rm "$volume" >/dev/null 2>&1 || true
    docker network rm "$net" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker rm -f "$app" "$db" >/dev/null 2>&1 || true
docker volume rm "$volume" >/dev/null 2>&1 || true
docker network rm "$net" >/dev/null 2>&1 || true

sql() { docker exec "$db" psql -U healthlog -d healthlog -tAX -c "$1"; }
start_db() {  # $1: image. The data lives in $volume, so the engine can be swapped under it.
    docker run -d --name "$db" --network "$net" -e POSTGRES_USER=healthlog -e POSTGRES_PASSWORD="$pg_password" \
        -e POSTGRES_DB=healthlog -v "$volume:/var/lib/postgresql/data" "$1" >/dev/null
    until docker exec "$db" pg_isready -U healthlog -d postgres >/dev/null 2>&1; do sleep 1; done
    sleep 2  # on a fresh volume the image restarts Postgres once after initdb
    until docker exec "$db" pg_isready -U healthlog -d postgres >/dev/null 2>&1; do sleep 1; done
}
swap_db() {  # $1: image
    docker stop -t 30 "$db" >/dev/null && docker rm "$db" >/dev/null
    start_db "$1"
}
ext() { sql "select extversion from pg_extension where extname = '$1'"; }
update_templates() {  # template1 (which new databases copy) and postgres follow the engine too; deploy.sh does the same
    for d in template1 postgres; do
        docker exec "$db" psql -U healthlog -d "$d" -tAXq -c "alter extension timescaledb update" 2>/dev/null || true
    done
}
available() { sql "select default_version from pg_available_extensions where name = '$1'"; }
counts() {
    for t in raw_ingest metric_samples sleep_sessions workouts state_of_mind companion.events companion.observations; do
        printf '  %-24s %s\n' "$t" "$(sql "select count(*) from $t" 2>/dev/null || echo '(no table)')"
    done
}

echo "== restore $(basename "$dump") into $db_image"
docker network create --internal "$net" >/dev/null
start_db "$db_image"
docker exec -i "$db" psql -U healthlog -d postgres -q < "$roles" 2>&1 | grep -v "already exists" || true
sql "select timescaledb_pre_restore()" >/dev/null
docker exec -i "$db" pg_restore -U healthlog -d healthlog < "$dump" 2>&1 \
    | grep -Ev 'circular foreign-key|^pg_restore: (detail|hint)|already exists' || true
sql "select timescaledb_post_restore()" >/dev/null
echo "schema before: $(sql 'select version_num from alembic_version')"
counts
restored=$(counts)

if [ -n "$db_image_to" ]; then
    echo "== engine $db_image -> $db_image_to (same data; timescaledb $(ext timescaledb), vector $(ext vector))"
    docker image inspect "$db_image_to" >/dev/null 2>&1 || docker pull -q "$db_image_to" >/dev/null
    swap_db "$db_image_to"
fi

echo "== HealthLog $image (migrations run on start)"
docker image inspect "$image" >/dev/null 2>&1 || docker pull -q "$image" >/dev/null
docker run -d --name "$app" --network "$net" \
    -e DATABASE_URL="postgresql+psycopg://healthlog:$pg_password@$db:5432/healthlog" \
    -e INGEST_SECRET=rehearsal-only -e TZ="$tz" -e NOTIFY_TOKEN= -e PUID="$(id -u)" -e PGID="$(id -g)" \
    -v "$cfg:/config" "$image" >/dev/null
i=0
until docker exec "$app" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" \
    >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -gt 180 ]; then
        echo "HealthLog did not become healthy in 3 minutes; last log lines:"
        docker logs --tail 40 "$app"
        exit 1
    fi
    sleep 1
done
echo "schema after:  $(sql 'select version_num from alembic_version')"
if [ -n "$db_image_to" ]; then
    have=$(ext timescaledb)
    want=$(available timescaledb)
    [ "$have" = "$want" ] || { echo "timescaledb is $have after HealthLog's start, the image offers $want"; exit 1; }
    sql "alter extension vector update" >/dev/null
    update_templates
    echo "extensions:    timescaledb $have, vector $(ext vector); template1 and postgres updated too"
fi
for cmd in ${RUN:-}; do
    echo "-- healthlog $cmd"
    docker exec "$app" healthlog "$cmd" 2>&1 | tail -4
done
counts
docker logs "$app" 2>&1 | grep -iE "error|traceback|fail" | grep -v "INFO" | head -20 || true

echo "== Companion against the migrated copy"
companion() {
    docker run --rm --network "$net" -e TZ="$tz" \
        -e DATABASE_URL="postgresql+psycopg://companion:$companion_password@$db:5432/healthlog" \
        healthlog-companion:dev "$@"
}
companion check-upstream
companion refresh | tail -3

if [ -n "$db_image_to" ]; then
    # The refresh rewrites the Companion's own tables, so only HealthLog's are compared; the Companion's were
    # compared above, before it ran.
    after=$(counts)
    hl() { echo "$1" | grep -v companion; }
    [ "$(hl "$restored")" = "$(hl "$after")" ] || { echo "row counts changed across the engine move"; exit 1; }
    echo "== a backup written on $db_image_to restores on $db_image_to"
    docker stop "$app" >/dev/null
    docker exec "$db" pg_dump -U healthlog -d healthlog -Fc > "$cfg/healthlog-rehearsal.dump"
    cp "$roles" "$cfg/roles-rehearsal.sql"
    DB_CONTAINER="$db" NO_STOP=1 "$repo/companion/scripts/restore.sh" "$cfg/healthlog-rehearsal.dump" --replace-live-data
    [ "$after" = "$(counts)" ] || { echo "a backup taken on the new engine did not restore the same rows"; exit 1; }
    echo "new-engine backup ok: timescaledb $(ext timescaledb), same row counts"

    echo "== rollback rehearsal: template1 and postgres back first, then $db_image, then restore.sh from $(basename "$dump")"
    DB_CONTAINER="$db" "$repo/companion/scripts/prepare_engine_rollback.sh" "$db_image"
    swap_db "$db_image"
    DB_CONTAINER="$db" NO_STOP=1 "$repo/companion/scripts/restore.sh" "$dump" --replace-live-data
    [ "$restored" = "$(counts)" ] || { echo "rollback did not restore the same row counts"; exit 1; }
    echo "rollback ok: $db_image, timescaledb $(ext timescaledb), same row counts as the backup"
fi
echo "== rehearsal passed for HealthLog $target${db_image_to:+ on $db_image_to}"
