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
