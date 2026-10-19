#!/bin/sh
# The one way to change what runs live. Every deploy starts with a fresh backup and stops at the first failure.
#
#   companion/scripts/deploy.sh companion           # rebuild and restart the Companion from this checkout
#   companion/scripts/deploy.sh healthlog <tag>     # move HealthLog to <tag>, rehearsed on a copy first
#   RUN="rederive-state-of-mind rederive-sleep" companion/scripts/deploy.sh healthlog <tag>
#
# healthlog: backup → rehearsal on a copy of that backup (upgrade_rehearsal.sh) → pin HEALTHLOG_VERSION in .env →
# restart HealthLog (its migrations run) → RUN commands → Companion contract check and refresh.
# If anything fails after the live step, restore.sh with the backup printed below puts the data back.
set -eu

what=${1:?usage: deploy.sh companion | healthlog <tag>}
repo=$(cd "$(dirname "$0")/../.." && pwd)
here=$(cd "$(dirname "$0")" && pwd)
backup_dir=${BACKUP_DIR:-/mnt/backup/healthlog}
compose() { docker compose -f "$repo/docker-compose.yml" -f "$repo/compose.local.yml" -f "$repo/compose.companion.yml" "$@"; }
env_value() { grep -E "^$1=" "$repo/.env" | tail -1 | cut -d= -f2-; }
healthy() { docker exec "$1" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" \
    >/dev/null 2>&1; }
wait_healthy() {
    i=0
    until healthy "$1"; do
        i=$((i + 1))
        if [ "$i" -gt 180 ]; then
            echo "$1 did not become healthy in 3 minutes"
            docker logs --tail 40 "$1"
            exit 1
        fi
        sleep 1
    done
}

echo "== backup"
"$repo/backup.sh"
dump=$(ls -1t "$backup_dir"/db/healthlog-*.dump | head -1)
previous=$(env_value HEALTHLOG_VERSION || true)
trap 'echo; echo "!! deploy stopped. To put the data back: companion/scripts/restore.sh $dump --replace-live-data"; [ -n "${tag:-}" ] && echo "   and set HEALTHLOG_VERSION=${previous:-latest} in .env"' EXIT

case "$what" in
companion)
    echo "== Companion from $(git -C "$repo" rev-parse --short HEAD)"
    compose up -d --build --force-recreate companion-web companion-jobs
    wait_healthy healthlog-companion
    ;;
healthlog)
    tag=${2:?usage: deploy.sh healthlog <tag>}
    echo "== rehearsal of HealthLog $tag on a copy of $(basename "$dump")"
    "$here/upgrade_rehearsal.sh" "$tag" "$dump"
    echo "== HealthLog ${previous:-latest} -> $tag"
    if grep -qE '^#?HEALTHLOG_VERSION=' "$repo/.env"; then
        sed -i -E "s|^#?HEALTHLOG_VERSION=.*|HEALTHLOG_VERSION=$tag|" "$repo/.env"
    else
        echo "HEALTHLOG_VERSION=$tag" >> "$repo/.env"
    fi
    compose pull -q healthlog
    compose up -d healthlog
    app=$(compose ps -q healthlog)
    wait_healthy "$app"
    for cmd in ${RUN:-}; do
        echo "-- healthlog $cmd"
        docker exec "$app" healthlog "$cmd" 2>&1 | tail -4
    done
    ;;
*)
    echo "unknown target: $what" >&2
    exit 2
    ;;
esac

echo "== verify"
docker exec healthlog-companion companion check-upstream
docker exec healthlog-companion companion refresh | tail -1
trap - EXIT
echo "== deployed. Backup taken before this deploy: $dump"
