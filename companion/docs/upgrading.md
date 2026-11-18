# Deploying, upgrading and rolling back

Every change to what runs live goes through one script, and every deploy
starts with a fresh backup. The nightly backup (04:30, `backup.sh`, 14 kept)
is a safety net, not part of a deploy: a change at 3 pm needs a backup from
3 pm.

## The scripts (`companion/scripts/`)

| Script | What it does |
|---|---|
| `deploy.sh companion` | backup → rebuild and restart the Companion from this checkout → contract check and refresh |
| `deploy.sh healthlog build` | the same, but HealthLog is built from this checkout as `healthlog-local:<commit>` instead of pulled. **This is how live runs now** |
| `deploy.sh healthlog <tag>` | backup → **rehearsal** on a copy of that backup → pin `HEALTHLOG_VERSION=<tag>` in `.env` → restart HealthLog (its migrations run) → `RUN` commands → contract check and refresh |
| `upgrade_rehearsal.sh <tag>` | restore a backup into a throwaway TimescaleDB on a network with no route out, run HealthLog `<tag>` on it, then the Companion's contract check and refresh; prints schema version and row counts before and after. Nothing live is touched. `KEEP=1` leaves the copy up |
| `restore.sh <dump> --replace-live-data` | put the live database back to a backup (HealthLog and the Companion together) |

`RUN="rederive-state-of-mind rederive-sleep"` passes re-derive commands a
release asks for, to both the rehearsal and the live deploy.

`backup.sh` lives at the repository root and isn't committed (it reads
`.env`). The scripts call it, so a machine without it can't deploy.

## Folding in upstream changes (how we upgrade now)

Since 2026-10-19 live runs HealthLog **built from this fork**, not his
published image. `compose.local.yml` points the `healthlog` service at
`${HEALTHLOG_IMAGE}:${HEALTHLOG_VERSION}`, and `deploy.sh healthlog build`
sets both (`healthlog-local` and the commit). His changes arrive as a merge:

1. `git fetch upstream && git checkout -b feature/sync-upstream-<date> main`
2. `git merge upstream/dev` (or a release tag). Read
   `git diff HEAD^1 HEAD -- backend/migrations` and the release notes for
   re-derives the change asks for.
3. `RUN="…" companion/scripts/upgrade_rehearsal.sh` against an image built
   from the branch (`docker build -f backend/Dockerfile -t healthlog-local:<commit> .`,
   then `HEALTHLOG_IMAGE=healthlog-local companion/scripts/upgrade_rehearsal.sh <commit>`).
4. Fork PR, green CI (his backend tests run too), merge.
5. On `main`: `RUN="…" companion/scripts/deploy.sh healthlog build`.

**Grafana dashboards with our UIDs.** Upstream's
`grafana/dashboards/sleep-activity.json` and `all-metrics.json` are his
versions of ours, with the same UIDs. Both folders are mounted, so two files
with one UID would leave Grafana to pick one. Remove his two in the sync
merge (`git rm grafana/dashboards/sleep-activity.json
grafana/dashboards/all-metrics.json`). If a later sync shows a
modify/delete conflict on them, read his change, port real bug fixes into
`companion/grafana/build.py`, and keep the delete.

**Upstream's optional Grafana** (since #137): `docker-compose.yml` has a
`grafana` service under `--profile grafana`, with a published port and one
dashboard mount. `compose.local.yml` resets its profile and port and
overrides its volumes, so ours always runs, is published by
`grafana-edge`, and mounts both dashboard folders once. Keep those three
lines when a sync touches either file.

### Moving the database engine

HealthLog updates the extension on start (`app.db_extensions`), but an
engine move is still a deploy of its own. `compose.local.yml` holds
`healthlog-db` on `HEALTHLOG_DB_IMAGE` (set in `.env` by the move; the
default is the current engine), so an upstream bump of the image in
`docker-compose.yml` changes nothing until we move. The move:

```bash
companion/scripts/deploy.sh database timescale/timescaledb:2.31.0-pg16
```

Best right after the 04:30 nightly backup. It takes a fresh backup, then
rehearses on a copy of it (`upgrade_rehearsal.sh` with `DB_IMAGE_TO`):

1. Restore into the old engine (a TimescaleDB dump restores only into the
   extension version that wrote it).
2. Restart the copy on the new engine with the same data; HealthLog's start
   updates the extension; pgvector, `template1` and `postgres` follow.
   HealthLog's row counts must not change; the Companion's contract check
   and refresh run.
3. A backup taken on the new engine must restore on it (so the nightly
   backups stay good after the move).
4. The rollback: `prepare_engine_rollback.sh` puts `template1` and
   `postgres` back on the old version, the copy goes back to the old
   engine, and `restore.sh` puts the backup back with the same rows.

Only then does it stop what uses the database, set `HEALTHLOG_DB_IMAGE`,
recreate `healthlog-db`, and make the same checks live. Downtime is a
minute or two.

**Why the extra steps.** A new database copies `template1`'s extension
version, and the old engine can't open a database whose extension is newer
than its libraries ("could not access file timescaledb-2.31.0"). So
`restore.sh` updates the extension in the fresh database before restoring,
and a rollback first takes `template1` and `postgres` back.

**Rolling back** (the deploy prints this if it stops):
`prepare_engine_rollback.sh <old image>` (only if the new engine already
runs), set `HEALTHLOG_DB_IMAGE` back, `up -d healthlog-db`, then
`restore.sh <backup from before the move> --replace-live-data`.

**After a move:** set the default in `compose.local.yml` and the image in
the companion workflows to the new tag (`test.sh` reads it from
`compose.local.yml` and replaces an older test database).

**Done 2026-11-18:** 2.17.2 → 2.31.0 (upstream #130), PostgreSQL 16.6 →
16.15, pgvector 0.7.2 → 0.8.1. Rehearsed on the 12:03 backup and again on
the 12:50 one inside the deploy (6.0 M samples, same rows; new-engine
backup and rollback both restored the same rows), then moved live in
about two minutes of downtime. Backup from just before:
`healthlog-20261118-125023.dump` (restores only into 2.17.2; see Rolling
back above).

The path check (R1) compares against `upstream/dev`, so after a sync only
our own paths show as changed. Nothing is pulled from his registry, so
nothing changes until we merge and deploy.

## Upgrading HealthLog from his published images

HealthLog's tables are not a contract: they change for correctness fixes,
new data types, storage and performance (#107). So:

1. **Pin.** Live runs the version in `HEALTHLOG_VERSION` (`.env`), never a
   moving tag. Nothing on this machine pulls images on its own.
2. **Choose a release.** Read the release notes and
   `git log <old>..<new> -- backend/migrations` for tables we read
   (`app/upstream.py`). Note any re-derive the release asks for.
3. **Rehearse.** `RUN="…" companion/scripts/upgrade_rehearsal.sh <tag>`.
   It must end with "rehearsal passed". Compare the counts: nothing we
   already have may shrink unexpectedly.
4. **Deploy.** `RUN="…" companion/scripts/deploy.sh healthlog <tag>`. It
   rehearses again on a fresh backup, then applies.
5. If the deploy stops, it prints the backup to restore.

## Rolling back

1. `companion/scripts/restore.sh <dump> --replace-live-data`. This stops the
   stack, replaces the `healthlog` database from the dump, and leaves the
   stack stopped.
2. Set `HEALTHLOG_VERSION` in `.env` back to the version that wrote that
   backup (a newer image would migrate it forward again).
3. `docker compose -f docker-compose.yml -f compose.local.yml -f compose.companion.yml up -d`.

Anything ingested after the backup is in Health Auto Export's history and
can be re-sent; anything logged in the Companion after the backup is lost.
So keep the time between backup and rollback short.

## What was tested (2026-10-19)

On a copy of the 2026-10-19 04:30 backup (1.6 GB database, 5.8 M samples):

- **Restore:** the backup restores into a fresh TimescaleDB 2.17.2.
- **Upgrade v0.6.1 → `dev`:** schema `0021` → `0023` in about a minute.
  `rederive-state-of-mind` filled 30 State of Mind entries from the raw
  archive. `rederive-sleep` (#113) took sleep from 5 nights to 25. The
  Companion's contract check passed, and its refresh found 100 more day
  values, with 32 of 87 series now eligible instead of 27.
- **Rollback:** `restore.sh` put the upgraded copy back to `0021` in 29 s,
  with identical row counts.
- **Fork build:** upstream `dev` (aa27590) merged into the fork and built as
  `healthlog-local:439fd51` gave the same results as his `dev` image.
