# Next steps: picking this up again

A handoff note: where things stand, what you need to do (no code), how to
set up a machine to work on it, and the work queue in order. Strategy is in
[`roadmap.md`](roadmap.md), the milestone checklist in [`plan.md`](plan.md),
risks in [`risks.md`](risks.md), rules in [`../CLAUDE.md`](../CLAUDE.md).

*Last updated 2026-10-19.*

## 1. Where things stand

| Piece | State |
|---|---|
| Fork `main` (`JHenzi/healthlog-ml`) | upstream `main` as of its #106 release (includes #104/#105) + Companion M1, M2, M4 part 1, M5 v1 (fork PRs #1–#4, all CI green). Upstream's #108–#110 are on their `dev` and arrive with their next release. |
| Upstream PRs | #104, #105 (backfill split) and #108 (time zone) **merged** into `anym001/healthlog:dev`; #111 (State of Mind) **merged** on 2026-10-18, with the maintainer's follow-ups in #112. The live HealthLog runs the released `:latest` image, which is still at migration 0021, so `public.state_of_mind` doesn't exist there yet |
| Live services | `healthlog-companion` (web, `127.0.0.1:8020`) and `healthlog-companion-jobs` (04:10 contract check, 04:15 refresh + analysis), built from the fork's `main` |
| Companion DB | schema `companion`, migrations up to `0004_trackers`; role `companion` read-only on HealthLog; password in `.env` as `COMPANION_DB_PASSWORD` |
| Data | 76 daily series (1,834 day values since 2026-07-15), 30 State of Mind entries, 0 trackers yet |
| Insights | engine live and validated; 0 findings yet: only 26 of 76 series have ≥ 21 days, and pairs overlap on ~25 days |

## 2. Your to-dos (no code)

In order of how much they unblock:

1. **Set the Companion password**
   ```bash
   docker exec -it healthlog-companion companion set-password
   ```
2. **Put HTTPS in front.** Sign-in needs it, because the session cookie is
   `Secure`. Tailscale is the simplest (untested here):
   ```bash
   tailscale serve --bg --https=8443 http://127.0.0.1:8020
   ```
   Then open `https://<host>.<tailnet>.ts.net:8443` on the phone.
3. **Sleep history: nothing to re-import.** Apple Health has no sleep before
   2026-09-24, and every night since is already stored. Sleep reaches the
   56 days the spread-over-days analysis needs in mid-November. To import any
   other manual export, drop it in `config/import/` and name the file:
   ```bash
   docker exec healthlog-healthlog-1 healthlog backfill /config/import/<file>.json
   docker exec healthlog-companion companion refresh
   ```
4. **Add two HAE automations** (REST API, same URL and secret as the Health
   Metrics one):
   - **Workouts**: HealthLog has 0 today.
   - **State of Mind**: today mood only arrives with manual exports. The
     last one landed on Oct 16.
5. **Create a few trackers** at `/trackers` (coffee, a 1–5 productivity scale,
   whatever you're curious about), pin them for one-tap logging, and do the
   evening review at `/review`. Self-tracked data only starts counting once
   it exists.
6. **Optional, HealthLog recompute after the time-zone change** (plan M0,
   unverified):
   ```bash
   docker exec healthlog-healthlog-1 healthlog analyze
   docker exec healthlog-healthlog-1 healthlog rederive-stress
   docker exec healthlog-healthlog-1 healthlog rederive-body-battery
   docker exec healthlog-companion companion refresh
   ```

## 3. Setting up a machine to work on it

### Dependencies

| Tool | Why | Install (Debian) | Status on the server |
|---|---|---|---|
| Docker + compose plugin | runs everything, including the tests | `apt install docker.io docker-compose-plugin` | installed |
| git, with `origin` = the fork and `upstream` = `anym001/healthlog` | syncing and PRs | `git remote add upstream https://github.com/anym001/healthlog.git` | set up |
| GitHub CLI `gh`, logged in as `JHenzi` | PRs, CI status | `apt install gh` then `gh auth login` | installed (it went missing once, reinstalled 2026-10-17) |
| *optional:* `python3.13-venv` | run tests without Docker | `sudo apt install python3.13-venv` | **not installed** (use the Docker runner below) |

Python packages are pinned in `companion/requirements*.txt`: FastAPI,
SQLAlchemy, Alembic, psycopg, argon2-cffi, numpy, pandas, scipy, ruff and
pytest. Nothing needs installing on the host: the image and the test runner
install them inside containers. With a venv instead:

```bash
cd companion && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
```

### Tests and lint

```bash
companion/scripts/test.sh                     # ruff + all suites, ~35 s
companion/scripts/test.sh tests/unit -x       # extra args go to pytest
STATS_SEEDS=200 companion/scripts/test.sh tests/stats   # the engine's validation suite at full strength
sh companion/scripts/check_paths.sh upstream/dev       # R1: only our paths changed
```

`test.sh` starts or reuses a throwaway TimescaleDB, `healthlog-testdb` on
127.0.0.1:55432. **Never point the suite at the live database**: it migrates
schemas down and up. `conftest.py` refuses any database name not ending in
`_test`. The suite runs HealthLog's own migrations from `backend/`, so the
contract tests check against the real upstream schema.

### Deploying a change

```bash
companion/scripts/deploy.sh companion
```

It takes a fresh backup, rebuilds and restarts both Companion containers
(`companion-web` applies new migrations when it starts), then runs the
contract check and a refresh. HealthLog upgrades, rehearsals and rollback:
[`upgrading.md`](upgrading.md).

### Working agreement

- **Branches and PRs:** a branch per slice (`feature/companion-…`), PR into
  the fork's `main`, merge when CI is green. Upstream work branches from
  `upstream/dev` and gets a PR there.
- **Docs:** updated in the same PR. When a milestone moves, update `plan.md`
  (checkboxes + a **Status** line), `roadmap.md`, and this file.
- **Syncing upstream** after each of their releases:
  ```bash
  git fetch upstream
  git switch main && git merge upstream/main
  ```
  Then rebuild, run `companion check-upstream`, and run `backup.sh`.

## 4. Work queue

### 4.1 Upstream (track A)

- **State of Mind (#111, merged to `dev`):** once a HealthLog release ships
  migration 0023 and the live image is updated, read `public.state_of_mind`
  through the contract instead of `raw_ingest`.
  To switch: add the table to `CONTRACT`, point `mood.sync_from_raw` at it
  (or replace it), and keep the `mood_entries` copy so history and the
  analysis don't change.
- **A4 unaggregated sleep:** fixed upstream in #113 (folds segments into
  nights, counts what it can't use, adds `healthlog rederive-sleep`). When a
  release ships it, follow *Folding in upstream changes* in
  [`roadmap.md`](roadmap.md) and run the re-derive.
- **Defensive sync (do next):** pin the HealthLog image to a release tag
  instead of `:latest` (`HEALTHLOG_VERSION=v0.6.1` in `.env`, the version
  running today), and add a nightly CI job that runs the contract
  check against `:dev`.
- **Read API v1 (A6):** offered by the maintainer, requirements on #107.
  Not scheduled.
- **A2 registry entries** (caffeine, alcohol, water, mindful minutes), as
  asked on #107. Not symptoms: see A5.
- **A5 Symptoms and Medications** (low priority: we track neither yet;
  symptoms first, medications second; shape proposed on #111). HAE exports these as their own data types,
  not Health Metrics, so they get a parser and table each, like State of
  Mind. The maintainer asked to discuss the shape first. Facts from HAE's
  export-format docs (no samples in our `raw_ingest` yet):
  - `data.symptoms[]`: `start`, `end` (equal for a point in time), `name`
    (e.g. "Headache"), `severity` (e.g. Mild/Moderate/Severe, not a closed
    set), `userEntered`, `source`. **No entry id**, unlike State of Mind.
  - `data.medications[]` (iOS 26+): `displayText`, `nickname`, `form`,
    `start`/`end` (the course), `scheduledDate`, `status` (Taken, Skipped,
    Snoozed, Not Logged, …), `isArchived`, `dosage` (unitless), `codings[]`
    (RxNorm/NDC). No entry id either.
  - Draft shape: `symptoms` keyed by (`start_time`, `name`, `source`), with
    `severity` kept as raw text; `medication_doses` keyed by (medication
    identity, `scheduled_time`). Open questions: whether `name` arrives
    localised (as workout names do), and how unscheduled as-needed doses are
    keyed. Symptoms first; medications after a real sample.

### 4.2 M3: weather (next build; it backfills, so findings come quickly)

- **Settings:** opt-in config with a coarse home location rounded to ~10 km
  (ENV or a `settings` row; never commit it).
- **Collector sidecar (design 2026-10-19):** the Companion itself makes no
  outbound calls. A separate `companion-collector` container fetches from
  Open-Meteo (daily and hourly temperature, humidity, pressure and its 24 h
  change, precipitation, cloud, wind, UV, air quality): a historical backfill
  since 2026-07-15, then a nightly increment. It has network access but no
  database credentials and no health data. It validates every value against
  a strict numeric schema and writes CSV files to a shared volume (read-only
  for the Companion). `httpx` goes in the collector's requirements only.
- **Network rule:** the Companion's egress tests stay as they are (no HTTP
  client, works offline). New tests: the collector's request carries only
  the rounded coordinates and dates, and a file that fails the schema is
  rejected, not partly read (R5, risks.md E2/E3).
- **Computed locally:** daylight (`astral`) and public holidays
  (`holidays`), no network.
- **Analysis:** features `weather.*` as their own family, one value per
  Companion day.
- **Done when:** weather exists for every day since 2026-07-15, Today
  mentions a notable pressure change, and the engine tests weather against
  everything else.

### 4.3 M4 part 2: capture on the phone

- **Track Shortcut:** the generic Shortcut, built by hand on the iPhone (it
  can't be generated). It gets the list from `GET /api/trackers` (a `read`
  token), shows *Choose from List*, asks per type, posts to `/api/log/<key>`,
  and speaks `message`. Share it via an iCloud link and document the import
  questions. **Test from the Watch**: does it route through the phone's
  Tailscale?
- **Installable web app:** `manifest.webmanifest`, a service worker, and an
  offline queue. Entries already carry device-generated `client_id`s, so
  retries are safe. The CSP allows only `script-src 'self'`, so the JS goes
  in `web/static/`.
- **Spans** (vacation, sick, travel): a table plus a 0/1 daily mask; the
  engine excludes span days by default.
- The Apple Health *Log Health Sample* recipes doc. (Ideas on the Trackers
  page are done.)
- **Day tags from the Shortcut and the API:** the web app toggles them
  (`POST /log/day_tags/tag`); the API doesn't log tags yet.
- **Minutes after waking** for time-of-day trackers, once sleep history is
  complete (§2.3).

### 4.3b Design

The warm look and the at-a-glance layer are live
([`design.md`](design.md)). Next:

- The glance treatment on Metrics (arrow and colour per row) and on the
  evidence page.
- Permanent per-tag colours, if shifting colours after a removal bothers
  anyone.

From the wireframes:

- ~~Evidence intervals~~: done 2026-10-19 (likely ranges, analysis-engine.md).
- **Explore** (3a).
- **Settings and data** (4b).
- **Experiments** (4a, with M9).

Regenerate the review page after UI changes with
`companion/scripts/design_preview/run.sh <dir>` (`SKIN=modernist` for the
old look), then republish it to https://claude.ai/artifact/5YEQVBwdtnxZx2SHLCD7pG.

### 4.4 M5 follow-ups and M6

- ~~Distributed lag models~~: done 2026-10-19 (analysis-engine.md, "Links
  spread over days"). Weather joins as an exposure when M3 lands.
- ~~Adjusted re-check~~: done 2026-10-19 (sleep and steps; analysis-engine.md).
  **Streaks and personal bests** as descriptive insights.
- **M6 within-day:** event-locked responses (coffee → steps, HR, stress over
  −60…+180 min against time-matched control days). Tracker entries already
  have timestamps.
- **Performance:** the pair loop is O(features²); about 7 s for a full
  refresh today. Watch it as trackers and weather add series (risks.md F1).

## 5. Things learned the hard way

- **HAE timestamps differ by section.** Most sections use `2026-06-15
  12:28:00 +0200`; `stateOfMind` uses ISO `2026-06-15T10:28:00Z`. Our mood
  parser accepts both.
- **With a 04:00 day boundary**, the DST switch (02:00) lands in the
  *previous* Companion day. In the US, 2026-03-07 is 23 h and 2026-10-31 is
  25 h.
- **Autocorrelation:** a plain rank test on consecutive days flagged ~30% of
  pure noise as a "change". Effective sample sizes fixed it; see
  [`analysis-engine.md`](analysis-engine.md). Any new method needs its
  validation suite before it ships (R8).
- **The R3 guard test** fails if a module other than `app/upstream.py`
  queries a HealthLog table. Name our tables so they never collide with
  HealthLog's (we use `mood_entries`, not `state_of_mind`).
- **`.gitignore` ignores `*.sql`** (dumps), with an exception for
  `companion/bootstrap/*.sql`. Keep using that folder for hand-written SQL.
- **Alembic's `fileConfig` disables existing loggers** unless
  `disable_existing_loggers=False`. The web process migrates and then logs,
  so this matters.
- **PyPI downloads are DNS-blocked on this network** (seen 2026-10-18):
  `files.pythonhosted.org` resolves to `::` (Pi-hole via Tailscale DNS),
  while `pypi.org` resolves fine. The image no longer needs it for its own
  install (a `companion` wrapper replaces `pip install -e .`), but a change
  to `requirements.txt` needs that host. Allow it in Pi-hole, or build
  elsewhere.
- **Don't pipe `docker compose up --build` through `tail`.** The pipe hid a
  failed build once, and the old image kept running. Check `docker compose
  build` on its own, or `set -o pipefail`.
- **Signing in over plain `http://`** fails because the cookie is `Secure`.
  For a quick local look only, set `COMPANION_COOKIE_SECURE=false` in `.env`
  and recreate `companion-web`. Turn it back on afterwards.
