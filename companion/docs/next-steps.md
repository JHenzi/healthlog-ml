# Next steps: picking this up again

A handoff note: where things stand, what you need to do (no code), how to
set up a machine to work on it, and the work queue in order. Strategy is in
[`roadmap.md`](roadmap.md), the milestone checklist in [`plan.md`](plan.md),
risks in [`risks.md`](risks.md), rules in [`../CLAUDE.md`](../CLAUDE.md).

*Last updated 2026-10-29.*

> **Back from the vacation pause on 2026-10-29.** The notes from the road are in
> [#45](https://github.com/JHenzi/healthlog-ml/issues/45) (`gh issue view 45 --comments`); what's
> still open from them is in §4.1 and §4.5.

## 1. Where things stand

| Piece | State |
|---|---|
| Fork `main` (`JHenzi/healthlog-ml`) | upstream `dev` as of #127 (synced 2026-10-29) + the Companion through reminders, the installable app and in-place forms (fork PRs #1–#50, CI green) |
| Upstream PRs | all ours merged: #104, #105, #108, #111 (State of Mind), #113, #117 (caffeine, HRV RMSSD), #118 (heart rate notifications, ECG), #126 (Outdoor/Indoor Cycling names). His #116 (symptoms, medications), #119 (German symptom names) #120 (telemetry off), #122 (workout `source` as an object, by marciotoze) and #127 (`rederive-workout-types`) are in too |
| Live HealthLog | `healthlog-local:c2131ca`, built from the fork (`deploy.sh healthlog build`), schema `0027_timescaledb_telemetry_off` |
| Live Companion | `healthlog-companion` (web, `127.0.0.1:8020`) and `healthlog-companion-jobs` (04:10 contract check, 04:15 refresh + analysis) |
| Companion DB | schema `companion`; role `companion` read-only on HealthLog; password in `.env` as `COMPANION_DB_PASSWORD` |
| Data | 106 daily series since 2026-07-15, weather (Cincinnati, since 2026-07-15) and the almanac included; sleep since 2026-09-24 (that is all Apple Health has); 3 heart rate notifications, 6 ECGs; 0 symptoms, 0 medications; workouts since 2026-10-28 (an HAE Workouts automation with workout metrics and route data on) |
| Insights | engine live and validated; 0 findings yet: 3,459 tests over 51 of 105 series on 2026-10-20 (R17 tests everything both ways). Sleep reaches 56 days (spread-over-days) in mid-November |
| Good-day score | live since 2026-10-20 (Overview card, `/good-days`); scored days need two of active, sleep, water and mood, so they grow with sleep and mood |

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
4. ~~**Turn on weather.**~~ Done (Cincinnati, since 2026-07-15). For reference: add your area to `.env` (it's rounded to ~10 km
   before anything is sent; `WEATHER_SINCE` is your first HealthLog day):
   ```bash
   WEATHER_LATITUDE=40.7
   WEATHER_LONGITUDE=-74.0
   WEATHER_SINCE=2026-07-15
   ```
   Then `companion/scripts/deploy.sh companion`. The collector backfills on
   its first start; `docker exec healthlog-companion-collector collector
   backfill --since 2026-07-15` repeats it by hand.
5. **Add two HAE automations** (REST API, same URL and secret as the Health
   Metrics one):
   - ~~**Workouts**~~: done 2026-10-28, with workout metrics and route data on.
   - **State of Mind**: today mood only arrives with manual exports. The
     last one landed on Oct 16.
6. **Rate each day** on the Overview: "How was today?" in the evening and
   the look back the next morning (built in since 2026-10-21, nothing to
   create). It is what the personal good-day weights will learn from (60–90
   days). Then **create a few trackers** at `/trackers` (coffee,
   productivity, whatever you're curious about), pin them for one-tap
   logging, and do the evening review at `/review`. Self-tracked data only
   starts counting once it exists.
7. **Optional, HealthLog recompute after the time-zone change** (plan M0,
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
- **Syncing upstream:** merge `upstream/dev` on a branch, rehearse, PR,
  deploy with `deploy.sh healthlog build`; the steps are in
  [`upgrading.md`](upgrading.md), *Folding in upstream changes*.

## 4. Work queue

### 4.1 Upstream (track A)

Follow upstream: merge his `dev` about monthly, or sooner for something we
need ([`upgrading.md`](upgrading.md), *Folding in upstream changes*).

- **Read API v1 (A6):** offered by the maintainer, requirements on #107. He
  mentions it again on #116 ("once that exists"). Not scheduled.
- **A2 registry entries** still open: alcohol, water, mindful minutes
  (caffeine went in with #117).
- **Sanitised fixtures he asked for (#118):** a German-locale ECG export
  (classification text is probably localised) and any heart rate
  notification other than `low_heart_rate_notification`. Only when one turns
  up in a real export.
- ~~**Workout names (#126)**~~: merged 2026-10-29, synced into the fork the
  same day. He keeps the hand-kept map, no fallback to Apple's label (a
  slugged label would split series when the phone language changes);
  `healthlog audit` lists unmapped names under "Unmapped workouts". His #127
  adds `healthlog rederive-workout-types`, run once after the deploy so the
  first two rides stop showing as "Other" in Grafana. The two lines in our
  `config/config.yaml` (`workouts.type_map`) are now redundant and harmless.
- **Medications:** his #116 keys doses on `(medication, dose_time)`. Nothing
  to do until we log any.

### 4.2 M3: weather (built 2026-10-20; waits on your location, §2)

- ~~**Day length and public holidays**~~: done 2026-10-20 as the almanac
  (`app/almanac.py`), with the moon and days until the next holiday (R17: no run-up window).
- **Weather along the workout route** (roadmap B14, plan M13): planned,
  with the privacy trade-off to debate first.
- **Weather on the Metrics pages** gets the same glance treatment as the
  rest once that lands (§4.3b).

### 4.3 M4 part 2: capture on the phone

- **Track Shortcut:** the generic Shortcut, built by hand on the iPhone (it
  can't be generated). It gets the list from `GET /api/trackers` (a `read`
  token), shows *Choose from List*, asks per type, posts to `/api/log/<key>`,
  and speaks `message`. Share it via an iCloud link and document the import
  questions. **Test from the Watch**: does it route through the phone's
  Tailscale?
- ~~**Installable web app**~~: done 2026-10-21 (`app/pwa.py`,
  `web/static/sw.js`, README *On your iPhone*): full screen from the Home
  Screen, saved page copies with a "Saved 9:42 · checking for updates…" note,
  a loading bar, and versioned static files. Still to do: an **offline
  queue** for entries logged without a connection (entries already carry
  `client_id`s, so retries are safe).
- ~~**Reminders at 10 AM and 7 PM**~~: built 2026-10-22 (`app/push.py`,
  `app/reminders.py`, the courier in `collector/collector.py`, README
  *Reminders*). Original notes: 7 PM for "How was
  today?" and the evening log, 10 AM for the look back. Web Push works for a
  Home Screen app on iOS 16.4 and later, and Tailscale doesn't stand in the
  way, because the push goes server → Apple → phone. But the server has to
  reach Apple's push service: a new outbound call, so it's **opt-in** like
  the weather (R5, privacy.md), and it needs VAPID keys in `.env`, a
  permission tap inside the installed app, and a job that sends at the
  times set. Until then, an iPhone Shortcuts automation at those times
  (*Ask for Number* → `POST /api/log/day_rating`, docs/api.md) works with no
  server change.
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

### 4.3c Grafana extras

Two extra dashboards are live since 2026-10-21 (`companion/grafana/`): Sleep &
Activity, and All Metrics (no dropdowns). They read only HealthLog's own
views. Offered upstream on 2026-10-21 as an issue with screenshots from
synthetic data (anym001/healthlog#121; images in `companion/grafana/screenshots/`).
If the maintainer wants them, open a PR from `upstream/dev` adding the two JSON
files to `grafana/dashboards/`, without touching his three; feedback on the
issue goes into `build.py` first.

- **An overlap dashboard** (asked 2026-10-21): Sleep & Activity, expanded.
  **Sleep is the base line**, and a dropdown overlays **any other series**:
  steps, exercise, mood, the day rating, the good-day score, weather, and
  your own trackers and tags. Both lines are on one timeline, each ranked
  against your own days so they share a scale (as Sleep & Activity does),
  with the next day lined up after each night. It's two lines you choose,
  not everything at once: All Metrics covers everything. Sleep as the base
  is a presentation choice (R17 allows that), not an analysis assumption;
  the engine still tests every pair. It belongs in the Companion, not
  Grafana, because Grafana can't see the rating, mood or trackers. It's the
  default view of the Explore page (§6), and it may be worth letting the
  base line be swapped too.

### 4.4 M5 follow-ups and M6

- ~~Distributed lag models~~: done 2026-10-19 (analysis-engine.md, "Links
  spread over days"). Every ordered pair since 2026-10-20 (R17).
- ~~Adjusted re-check~~: done 2026-10-19; since 2026-10-20 it allows for
  the series the run found linked to both sides, not a fixed list (R17).
- ~~Streaks and records~~: done 2026-10-20, "Worth noting" on the Overview
  (`app/highlights.py`): tracker streaks (3+ days) and quiet runs (7+ recorded
  days), and records over 60+ days of data. Records wait for 60 days, so the
  first appear in mid-November for sleep. Later: a streak against your own
  30-day median for key metrics, if the notes feel too sparse.
- ~~Good-day score and best days~~: done 2026-10-20 (`app/goodday.py`,
  analysis-engine.md). Next for it:
  - **Personal weights** (M7): equal weights are the standard; a learned
    score, anchored on your own rating of the day, sits next to it and is
    shown only when it predicts better (analysis-engine.md, "Learned
    weights"). Anchored on the built-in day rating (since 2026-10-21).
  - **Day rating follow-ups:** show it next to the score on `/good-days`
    (does the computed score agree with how the day felt?); an evening
    Shortcut for `POST /api/log/day_rating`; a reminder once M11 has push.
  - **Compare with others** (M12, roadmap B13): offline reference figures,
    an anonymous summary, and others' to compare with. How summaries are
    exchanged is an open question (privacy.md, *Planned*).
  - **Goals as a setting** (sleep hours, water): a part could then read
    "met / not met" instead of a rank. Only when you set one; nothing is
    guessed.
  - **M7 predicts the score** (next-day, with the features that pushed the
    prediction), once there are ~90 scored days.
  - Mood is the thinnest part: State of Mind only arrives when you log one.
  - **The parts are hand-picked** (raised 2026-10-21). Active, sleep,
    water and mood are this user's definition, coded in. Someone else's
    best days, or this user's later on, may hinge on a tracker or a metric
    that isn't a part. Planned: the **day rating is the outcome**, and the
    engine already tests it against every series. The score's parts become
    a setting (default: these four), and M7's learned score may draw on any
    series that predicts the rating, not only the four.
- **M6 within-day:** event-locked responses (coffee → steps, HR, stress over
  −60…+180 min against time-matched control days). Tracker entries already
  have timestamps.
- **Performance:** the pair loop is O(features²); about 7 s for a full
  refresh today. Watch it as trackers and weather add series (risks.md F1).

### 4.5 Found along the way (do when convenient)

- ~~**Coffee and beer counted as water (#45)**~~: done 2026-10-29. Water
  Llama writes each drink to Apple Health twice: as caffeine or alcohol,
  and as a water sample at the same instant (about +71 mL per 50 mg of
  caffeine, −142 mL per standard drink). Those samples are now their own
  series, *Water from coffee* and *Water from alcohol*
  (`hl.dietary_water_from_<drink>`, in the drink's family), and *Water*
  holds plain water only; the three add up to Apple Health's total. 10/23:
  water 119, from coffee 142, from alcohol −308 mL. HealthLog's own daily
  sum (Grafana) still mixes them; an upstream question if it matters.
- **Water Llama's total doesn't reach Health:** it showed 39.9 oz consumed
  on 10/23, HAE delivered about 9 oz. Check Apple Health → Water for that
  day to see which side drops the rest.

- **Purge a tracker or tag (plan M11):** removing a tag or archiving a
  tracker keeps its history (fixed 2026-10-20: removed tags used to vanish
  from the analysis, archived trackers kept getting zeros). Offer an explicit
  "delete its entries too" with a confirmation, built on the same redaction
  as the diary purge (risks.md E5).

- **Features from HealthLog's new tables:** heart rate notifications and ECGs
  (counts per day, ECG average HR), symptoms (present or not, by slug, once
  logged). Each needs a contract entry (R3) and a `check-upstream` update.
- **Mood from `public.state_of_mind`:** HealthLog parses it since 0023. We
  still parse `raw_ingest` ourselves (`mood.sync_from_raw`) so history and
  the analysis stay unchanged; switching means a contract entry and a check
  that both give the same entries.
- ~~**Grafana telemetry**~~: done 2026-10-20, turned off in `compose.local.yml`
  (upstream #120 documents the variables but doesn't ship our Grafana).
- **A change to upstream's `docker-compose.yml` recreates `healthlog-db`**
  on deploy (seen with #120's `TIMESCALEDB_TELEMETRY`): a few seconds of
  downtime, data safe on its volume.
- ~~**Weather missing from My Metrics**~~: the list only knew the original
  sources; weather and the almanac have their own groups since 2026-10-20.
- **Almanac, later:** more countries and regional holidays (states, Länder);
  day length as an analysed feature once there's a year of data (now the
  vacation and sick-day spans (M4 part 2) as the personal side of the
  calendar.
- **"Worth noting", driven by findings:** the threshold-based weather note
  and the holiday run-up note were dropped under R17 (they encoded our
  guesses). Instead: mention a series' latest value on the Overview only
  when the engine has reported a link between it and something of yours
  ("Pressure rose 9 hPa yesterday; for you, a rise tends to be followed by
  shorter sleep").
- **R17 cost to watch:** testing everything makes the FDR family bigger
  (more tests, a higher bar per finding). Expected and accepted; record the
  test count per run (`RunStats.tests`) as series are added.
- **Re-derives are slow:** each `rederive-*` re-reads every raw payload
  (~80 s each for 153 payloads). Fine now; worth a note to upstream if
  `raw_ingest` grows a lot.

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
