#!/bin/sh
# The one way to change what runs live. Every deploy starts with a fresh backup and stops at the first failure.
#
#   companion/scripts/deploy.sh companion           # rebuild and restart the Companion from this checkout
#   companion/scripts/deploy.sh healthlog <tag>     # move HealthLog to his published image <tag>, rehearsed on a copy first
#   companion/scripts/deploy.sh healthlog build     # build HealthLog from this checkout (healthlog-local:<commit>) and move to it
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
set_env() {
    if grep -qE "^#?$1=" "$repo/.env"; then
        sed -i -E "s|^#?$1=.*|$1=$2|" "$repo/.env"
    else
        echo "$1=$2" >> "$repo/.env"
    fi
}
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
previous_image=$(env_value HEALTHLOG_IMAGE || true)
trap 'echo; echo "!! deploy stopped. To put the data back: companion/scripts/restore.sh $dump --replace-live-data"; [ -n "${tag:-}" ] && echo "   and set HEALTHLOG_IMAGE=${previous_image:-ghcr.io/anym001/healthlog} HEALTHLOG_VERSION=${previous:-latest} in .env"' EXIT

case "$what" in
companion)
    echo "== Companion from $(git -C "$repo" rev-parse --short HEAD)"
    compose up -d --build --force-recreate companion-collector companion-courier companion-web companion-jobs companion-edge
    wait_healthy healthlog-companion
    ;;
healthlog)
    tag=${2:?usage: deploy.sh healthlog <tag> | build}
    image=ghcr.io/anym001/healthlog
    if [ "$tag" = build ]; then
        [ -z "$(git -C "$repo" status --porcelain -- backend root)" ] || { echo "backend/ or root/ has uncommitted changes" >&2; exit 2; }
        tag=$(git -C "$repo" rev-parse --short HEAD)
        image=healthlog-local
        echo "== build HealthLog from $tag"
        docker build -q -f "$repo/backend/Dockerfile" --build-arg APP_VERSION="fork-$tag" -t "$image:$tag" "$repo" >/dev/null
    fi
    echo "== rehearsal of HealthLog $image:$tag on a copy of $(basename "$dump")"
    HEALTHLOG_IMAGE=$image "$here/upgrade_rehearsal.sh" "$tag" "$dump"
    echo "== HealthLog ${previous_image:-ghcr.io/anym001/healthlog}:${previous:-latest} -> $image:$tag"
    set_env HEALTHLOG_IMAGE "$image"
    set_env HEALTHLOG_VERSION "$tag"
    [ "$image" = healthlog-local ] || compose pull -q healthlog
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
"$here/check_egress.sh"
docker exec healthlog-companion companion check-upstream
# No pipe here: a failing refresh must stop the deploy (a "| tail" once hid one).
out=$(docker exec healthlog-companion companion refresh 2>&1) || { echo "$out" | tail -20; exit 1; }
echo "$out" | tail -1
trap - EXIT
echo "== deployed. Backup taken before this deploy: $dump"
