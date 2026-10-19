# Architecture

How the Companion sits next to HealthLog without breaking it. The full design
is in [`companion-app-design.md`](companion-app-design.md) §8. This file
describes what is built (M1, M2, M4 part 1 and M5 v1). The insight engine has its own
page: [`analysis-engine.md`](analysis-engine.md).

## Processes

```
iPhone / Watch ─ HAE ─► healthlog (upstream image, untouched) ─► schema public
                                                                     │ SELECT only
browser / Shortcut ─► companion-web (FastAPI, :8000) ─┬─► schema companion (read/write)
                      companion-jobs (APScheduler) ───┘
                              one Postgres/TimescaleDB instance (healthlog-db)
```

One image, two services, like HealthLog's web/scheduler split.
`companion-web` applies migrations, then serves pages and the API.
`companion-jobs` runs scheduled work: the 04:10 contract check and the 04:15
refresh (after HealthLog's 03:30 run, before its 04:30 backup), which ends
with the insight engine. A full refresh takes about 7 s on the live data. The
jobs service has a memory and CPU cap so it can't starve the database.

## Database isolation

- **Role `companion`** owns schema `companion` and has `SELECT` only on
  `public`, including tables HealthLog creates later (default privileges).
  Postgres itself enforces the read-only boundary. `bootstrap/bootstrap.sql`
  sets this up once, as the database owner.
- **No dependent objects:** no view, foreign key, trigger or function of ours
  references `public`. HealthLog's migrations drop and rebuild their own
  objects, so a dependency would make their upgrade fail.
  `tests/contract/test_isolation.py` checks `pg_depend` for this.
- **Own Alembic history:** `companion.alembic_version`, never touching
  HealthLog's `public.alembic_version`.

## The read contract

`app/upstream.py` is the only module that queries `public`. It lists every
table and column we read (`CONTRACT`), and reads only from base tables, never
from HealthLog's views. `check_upstream` verifies the contract on web
startup, in the nightly job and via `companion check-upstream`. If a check
fails, the affected Today line degrades with a visible note instead of
crashing the page. A test fails if any other module names a HealthLog table.

Current contract: `metric_samples`, `metric_registry`, `sleep_sessions`,
`stress_intraday`, `body_battery_intraday`, `workouts` and `raw_ingest`. We
read the intraday stress and energy tables rather than HealthLog's `*_daily`
tables because those use midnight days. Ours use the day boundary. The guard
test checks that no other module queries a contracted table or references
`public.`.

## The daily feature table

`daily_features` (`day`, `feature`, `value`) plus `feature_defs` are the one
table every analysis reads (design §4.1). `companion refresh` (`jobs.refresh`)
rebuilds them from scratch, so a changed rule applies to all history:

1. **Seed `metric_settings`** from HealthLog's registry. New metrics are
   added; rows you edited on the Metrics page are never overwritten.
2. **Copy State of Mind** entries into `mood_entries`. They come from
   `raw_ingest` with a cursor (each archived payload is read once),
   deduplicated by HAE's entry id, last copy wins. This is our own parser,
   and it accepts ISO 8601 and HAE's own timestamp format. When HealthLog
   stores State of Mind itself (PR #111), the reader switches to its table.
3. **Assemble features** (`features.assemble`, pure):

| Feature | From | Rule |
|---|---|---|
| `hl.<metric>` | `metric_samples` | per Companion day: one source (priority list → merged stream → busiest source), then the metric's aggregation, then its bounds (outside → missing) |
| `sleep.total_h`, `deep_h`, `core_h`, `rem_h`, `awake_h` | `sleep_sessions` | per wake date; the source with the most total sleep |
| `stress.mean` | `stress_intraday` | mean over measured minutes |
| `energy.low`, `energy.high` | `body_battery_intraday` | lowest / highest level |
| `workout.minutes` | `workouts` | per Companion day, one source |
| `mood.entries`, `valence_mean`, `valence_min`, `daily_valence`, `momentary_valence`, `label.<x>`, `assoc.<x>` | `mood_entries` | per Companion day; label and association counts are 0 only on days with at least one entry |

A day without data for a feature has no row. It is never stored as 0 (R7).
The full rebuild takes a few seconds on ~6M HealthLog samples.

## Capture: trackers and the event log

Trackers are rows (`trackers`). The set of *types* is code
(`app/trackers.py`): count, scale, check, quantity, duration, time, choice,
moment and tags. The type decides validation and daily features, so a new tracker
needs no migration. A tracker's type, unit, scale range and options lock once
it has data. Changing one creates a successor version, and the old tracker is
archived with its history (R12).

Every change is appended to **`events`** first (`log`, `edit`, `delete`,
`review`, `unreview`). This is the source of truth. `observations` and
`day_reviews` are derived from it (`capture.apply`), and `capture.rebuild`
replays the whole log. A randomized test checks that replaying gives exactly
the incremental state. Deletes are tombstones. Logging is idempotent on the
client id: the API takes it from the device, and every web form carries a
fresh one, so retries and double taps never double an entry.

Tracker features go into the daily feature table as `tracker.<key>.*`, one
family per tracker:

| Type | Features |
|---|---|
| count, quantity, duration | `.total`; counts also `.first_time` and `.last_time` (minutes after midnight, rolled past the day boundary) |
| check | `.any` |
| scale | `.mean`, `.max` |
| choice | one count per option |
| moment | `.count`, `.max_intensity`, `.first_time` |
| time | `.first_time` |
| any tracker with tags | `.tag.<slug>` per tag (1 picked, 0 not picked) |

Count, yes/no, choice and moment features are 0 only on reviewed days, or on
every day since the first entry for an "always logged" tracker. They never
zero-fill today. Scale and time features are never zero-filled.

**Day tags** (migration 0005) describe the day, not a measure ("meeting
heavy", "travel"). They live on one reserved tracker of type `tags`, key
`day_tags` (name "Day", so features read "Day: meeting heavy"), created with
the first tag. `trackers.tags` holds their display text; removing a tag
keeps its past entries in the event log. The web app no longer offers tags
on other trackers (the model still allows them). A picked tag is an observation
with `tag` set to its slug and no value; tapping it again tombstones it. A tag
is 1 on a day it was picked and 0 on a day the tracker was otherwise used or
the day was reviewed (the tag was in front of you and not picked); unknown
otherwise. Tags share their tracker's family, so "Work day" is never related
to its own "meeting heavy" tag.

New trackers assume what they can: the key comes from the name and every
new rating is 1–10, 10 high. Every active tracker shows in Quick add and the
daily log (`pinned` and `in_review` are no longer read by the web app). No
tracker says which way is better: the analysis finds the direction, and
ratings use one light-to-dark ramp. Older trackers keep
their own scale. Logging an earlier day without a time records it at midday
of that day.

**What logging shows is the day's number, not the entries.** Counts, amounts
and minutes show the day's total with − (tombstone the latest entry) and +.
A rating, yes/no or pick-one has one value a day: a new tap replaces it and
tapping the same value clears it (`capture.set_day_value`); the replaced
entries are tombstoned, so the event log keeps the full history. A tracker's
page keeps that history folded away, and logging from a Shortcut or another
app (URL, log-only tokens) is its own page, `/trackers/<key>/connect`. The
web forms no longer take a time; the API still does.

## Days

A Companion day runs from `DAY_BOUNDARY` (default 04:00) local time to the
same time the next day, in the configured `TZ` (`app/timeutil.py`). The same
rule exists in SQL (`sql_day_expr`), and a test checks both agree around the
boundary and across DST. With a 04:00 boundary, the 02:00 DST switch falls in
the day *before* the transition date: in the US, 7 March is 23 h and
31 October is 25 h in 2026. Sleep is the exception: a night belongs to the
calendar date you woke up.

## Sources

HealthLog can store the same metric from several devices. We never sum
across sources (R16). HealthLog's merged stream (empty source) wins when
present; otherwise the source with the most samples that day
(`today.pick_source`).

## Auth

- **Browser:** one argon2-hashed password → a random session cookie (`HttpOnly`,
  `Secure`, `SameSite=Strict`, only its SHA-256 stored), a per-session CSRF
  token on every form, a login CSRF cookie, and a persistent lockout after
  repeated failures.
- **API:** bearer tokens `hlc_…`, stored as SHA-256, scoped `all` / `read` /
  `log:<key>`, revocable one at a time.
- **Pages:** Jinja autoescaping, plus a strict CSP (`script-src 'self'`,
  `frame-ancestors 'none'`).
- **Proxies:** `X-Forwarded-For` is honoured only from `TRUSTED_PROXIES`, and
  only for log lines.
- **Later:** `proxy_header` mode (trusting an identity header from an
  authenticating proxy) comes in M11.
