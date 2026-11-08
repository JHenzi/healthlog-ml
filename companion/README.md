<p align="center"><img src="docs/design/icon.png" width="120" alt="The Companion icon: a light cross on a teal network of points"></p>

# Health and Discovery Companion

*The Companion*, for short. Our analysis engine and app, built in this fork
on top of [HealthLog](../README.md). HealthLog is
the data pipeline (Apple Health → TimescaleDB). The Companion reads its tables
**read-only**, keeps its own data in schema `companion`, and turns it into
plain-language sentences. Design: [`docs/companion-app-design.md`](docs/companion-app-design.md).
Rules: [`CLAUDE.md`](CLAUDE.md). Build plan: [`docs/plan.md`](docs/plan.md).

Everything runs on your own server. The Companion makes **no outbound
calls**: no telemetry, no cloud, no model APIs. The two opt-in exceptions
(weather, phone reminders) leave from separate containers that hold no health
data, and every deploy proves the rest can't reach the internet
([`docs/privacy.md`](docs/privacy.md)).

## What it does

In one line: it pulls your Apple Health data together with what you log
yourself and the world outside (weather, daylight, the moon, holidays),
turns it all into one number per day per series, and tells you, in plain
sentences with their evidence attached, what tends to go together in **your**
data. It has no built-in theory of what matters (rule R17): everything is
compared with everything, in both directions, and only what clears a strict
false-discovery bar is shown.

The app has five sections: **Overview**, **Discovery**, **Capture**,
**My Metrics** and **Trackers**.

### Overview: your day at a glance

- **Your day**: the built-in day rating. "How was today?" (1–10) in the
  evening, and a blind "Looking back, how was yesterday?" the next morning.
  Nothing to set up. Both ratings and the change between them become daily
  series like any other.
- **Good day**: today's good-day score (below) and its parts as coloured
  bars.
- **Compared with your usual**: tiles for last night's sleep and yesterday's
  HRV, resting heart rate, steps, stress, energy reserve and mood, each with
  ▲/▼ against your 30-day average and the number of days behind it. The same
  as sentences, if you prefer words.
- **Worth exploring**: the strongest current discoveries.
- **Worth noting**: streaks and personal records, as plain facts ("7 days in
  a row", "the highest of your 60+ days"), never judged good or bad.
- **Data for analysis**: a 30-day coverage strip, so gaps are visible, and
  any problem reading HealthLog's data, stated outright.
- **Quick add**: one tap for your pinned trackers.

### Discovery: what goes together in your data

- **Discoveries**, strongest first, grouped as *Relationships* (two series
  that move together the same day, the next day, or spread over the
  following week), *This week* and *This month* (a real change against the
  weeks before) and *Weekly rhythm* (a series that differs by weekday).
- Each one is a sentence such as "Higher X tends to be followed by lower Y
  the next day", with its **number of days**, a **strength** word, a
  **likely range** bar and a *Preliminary* tag under 30 days. The wording is
  association only: never *causes* or anything diagnostic (R10).
- **Re-checked**: a relationship is re-read after removing what else the
  run linked to both sides, and says whether it holds, fades or grows.
- **Earlier discoveries**: each run starts over, so a pattern near the bar
  can drop out after one more day of data. It isn't lost: it moves to a
  quieter list with the days it held, for 90 days, and moves back up if it
  clears the bar again. Current ones say *since* when they first appeared.
- **Evidence page** for each: the method in words, effect size, raw and
  adjusted p, effective days after allowing for day-to-day carry-over, and
  for links over days a bar per day 0–7 showing when the link peaks.
- **Good days**: a score per day from four equally weighted parts (active,
  sleep, water, mood), each ranked against your own history. A grid of the
  last two weeks coloured low → high, **your best days** (the top quarter),
  and **what your best days have in common**: series the analysis linked to
  the score, with their typical value on best days vs the rest.
- Runs every night at 04:15, or **Run it now**. Statistically: residuals
  after removing weekday profiles and trends, effective sample sizes, one
  Benjamini-Hochberg family at 10% over every test of a run, effect floors,
  and a validation suite that plants effects and confounders on synthetic
  data before any method ships (R8,
  [`docs/analysis-engine.md`](docs/analysis-engine.md)).

### Capture: logging the day

- **The day page** (today or any earlier day): the day rating, **day tags**
  (one tap each: "worked from home", "late meal", anything you add), every
  tracker with a control that fits its type, and a short **diary** entry.
  Diary text is never analysed and never logged.
- **Reviewed days**: marking a day reviewed is what lets an unlogged count
  or yes/no count as zero. Otherwise a forgotten entry stays *unknown*,
  never "none" (R7: missing is not zero).
- **Reminders** (optional): a push at 10:00 for the look back and at 19:00
  for the rating, skipped when already answered. Times are adjustable;
  **Send a test** checks the whole path.

### My Metrics: every series, readable

- A **tile per series**: the latest value, a 60-day sparkline, and a chip
  for where the latest day falls among all your own days ("high for you",
  "usual for you"), coloured clay → sand → moss. The colour means unusual
  *for you*, never good or bad. Under it, the 30-day average with ▲/▼ on the
  month before.
- **Counts and day tags** as rows of 30 day squares (filled on days they
  happened, hatched where nothing was recorded), most frequent first; ones
  you haven't used in 30 days fold away.
- **Mood** as one chart: a bar per day above or below neutral, with a tick at
  the day's lowest moment.
- **Water** as one stack on each water page: plain water and water from
  coffee above the line, what alcohol takes off below it, and the day's net
  (Apple Health's total). The analysis still keeps the three apart.
- Ordered sleep and Health first, then what you log, then outside data.
- **Each series' page**: a coloured calendar of the last 30 days, your
  average per weekday, and for HealthLog metrics the **settings** for how a
  day's value is formed (sum, average, lowest, highest), which sources to
  prefer (never added together, R16), plausibility bounds, and whether it's
  analysed.

What's there: all of HealthLog's metrics (not just its core ones), sleep and
its stages, stress and energy reserve, workout minutes, Apple Health State of
Mind (valence, every feeling and what it was about), the good-day score, the
day ratings, your trackers and tags, weather and the almanac.

### Trackers: measure anything

- **Kinds**: a count (coffee), a 1–10 rating, yes/no, an amount with a unit,
  minutes, a time of day, a pick-one (lunch at home / takeout / skipped), a
  moment with an intensity, or a day tag. Ratings are always 1–10 and
  coloured low → high; there's no "higher is better" setting, because the
  data finds the direction.
- **Opinionated setup**: a name and a kind, with ideas that fill in the
  form. A tracker's type and scale are locked once it has data; a change
  makes a successor, so history never silently changes meaning (R12).
- **Every entry is kept**: an append-only event log is the source of truth.
  Undo leaves a tombstone, and every daily series can be rebuilt from it.
- **History is editable**: a tracker's History lists every entry with
  **edit** (day, time, value) and **delete**. A fix is a new event next to
  the original, so nothing is overwritten. A rating, yes/no, pick-one or
  time can't be moved onto a day that already has one.
- **Log from anywhere**: each tracker has a **Connect** page with its own
  URL and a token that can log that tracker and nothing else, plus a
  **paste-ready prompt for the Shortcuts app's AI builder**. It builds a
  Shortcut named the way you'll say it ("Snap a stretching session"), so
  Siri, a HomePod, an NFC sticker or the Action button logs it and speaks
  the reply back. See *Logging from Shortcuts* below.
- **Import your history** from another tracking app: `companion import-days`
  brings in day-by-day tags, trackers and notes, never overwriting a day you
  logged here.

### Outside data

- **Weather and air quality** (opt-in): temperature, humidity, pressure and
  its change, rain, cloud, UV, wind, PM2.5 and AQI for your area, backfilled
  over your whole history from [Open-Meteo](https://open-meteo.com), with
  your location rounded to ~10 km first.
- **The almanac**, computed here with nothing fetched: day length, the moon,
  public holidays and days until the next one.

Both are analysed like everything else, so "rainy days go with shorter
sleep" can turn up, and so can its absence.

### On the phone

- **Installable app** (Add to Home Screen): full screen, opens instantly
  from a saved copy, and says how fresh it is ("Saved 9:42 · checking for
  updates…"). Signing out deletes the saved copies.
- Forms save **in place**: no reload, same scroll position, a double tap
  posts once.

### Also

- **Grafana dashboards** next to HealthLog's: *Sleep & Activity* (with a
  0–7 day shift and a gap correlation chart) and *All Metrics* (every
  metric, no dropdowns), in [`grafana/`](grafana/README.md).
- A **JSON API** for everything above, every route documented in
  [`docs/api.md`](docs/api.md) (R18).
- **Security**: password sign-in with lockout, CSRF on every form, a strict
  content security policy, hashed tokens with one scope each, and the web
  port on localhost only behind HTTPS.
- **Safe to run next to HealthLog**: read-only access to its tables through
  one read contract, checked at startup and nightly
  (`companion check-upstream`), and nothing that depends on its schema, so
  HealthLog upgrades stay its own business (R2, R3).

## Install

Prerequisites: HealthLog running from this repository's `docker-compose.yml`,
and `TZ` set in `.env` (the Companion refuses to start without it).

1. **Database role and schema (once).** Add a password for the Companion's
   database role to `.env`:

   ```bash
   echo "COMPANION_DB_PASSWORD=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')" >> .env
   ```

   Then create the role and schema. This needs HealthLog's database owner,
   and it's idempotent:

   ```bash
   set -a; . ./.env; set +a
   docker exec -i healthlog-db psql -q -U healthlog -d healthlog -v ON_ERROR_STOP=1 \
     -v companion_password="$COMPANION_DB_PASSWORD" < companion/bootstrap/bootstrap.sql
   ```

   It creates the `companion` role (SELECT-only on HealthLog's tables,
   including tables HealthLog adds later), the `companion` schema it owns, and
   the pgvector extension inside that schema. It creates nothing that
   depends on HealthLog's objects, so HealthLog's upgrades are unaffected.

2. **Start it**, layered on HealthLog's compose file:

   ```bash
   docker compose -f docker-compose.yml -f compose.local.yml -f compose.companion.yml up -d --build
   ```

   `companion-web` applies the Companion's migrations on start and serves on
   `127.0.0.1:8020` (`COMPANION_BIND`, `COMPANION_PORT`): this machine only,
   so reach it through Tailscale Serve or a reverse proxy. `companion-jobs`
   runs scheduled work.

3. **Set your password:**

   ```bash
   docker exec -it healthlog-companion companion set-password
   ```

4. **Check the read contract:**

   ```bash
   docker exec healthlog-companion companion check-upstream
   ```

## Settings (environment)

| Variable | Default | Meaning |
|---|---|---|
| `COMPANION_DB_PASSWORD` | *(required)* | password of the `companion` database role |
| `TZ` | *(required)* | your IANA time zone, e.g. `America/New_York` |
| `DAY_BOUNDARY` | `04:00` | local time at which one day ends and the next begins, so late nights count as the evening before |
| `COMPANION_PORT` | `8020` | host port for the web app |
| `COMPANION_BIND` | `127.0.0.1` | host address the port is published on. Keep it on localhost; set it to another address only if a reverse proxy on a different machine must reach it directly |
| `COMPANION_COOKIE_SECURE` | `true` | send the session cookie over HTTPS only; leave on in production |
| `TRUSTED_PROXIES` | private ranges | same meaning as HealthLog's: which peers may set `X-Forwarded-For` |
| `WEATHER_LATITUDE`, `WEATHER_LONGITUDE` | *(off)* | your home area, for weather. The collector rounds both to 0.1° (~10 km) before anything is sent. Leave unset to keep weather off |
| `WEATHER_SINCE` | 92 days ago | first day of the automatic backfill, e.g. `2026-07-15` (your first HealthLog day) |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` | *(off)* | reminders: the key pair from `companion push keys`. The private key is a secret |
| `VAPID_SUBJECT` | `https://github.com/JHenzi/healthlog-ml` | a contact the push services may use (a `mailto:` or `https:` URL; Apple refuses one at `localhost`) |
| `PUSH_ENABLED` | `false` | lets the courier deliver reminders; set `true` together with the keys |
| `HOLIDAYS_COUNTRY` | from `TZ` | public holidays for the almanac: `US`, `CA`, `GB` or `DE`, or `none`. A US, Canadian, UK or German time zone picks its country |

`SESSION_DAYS` (30), `LOGIN_MAX_FAILURES` (5) and `LOGIN_LOCKOUT_MINUTES` (15)
can also be set on the containers.

## HTTPS (required)

Sign-in needs HTTPS: the session cookie is `Secure`, and the installable web
app (from M4) needs a secure context. The Companion serves plain HTTP and
leaves TLS to whatever sits in front of it. It contains no code for any
particular proxy.

**Tailscale Serve**: on the Docker host,

```bash
tailscale serve --bg --https=8443 http://127.0.0.1:8020
```

Then open `https://<host>.<tailnet>.ts.net:8443` from any device on your
tailnet. Nothing is exposed to the internet. nginx or Caddy work the same way:
proxy to `127.0.0.1:8020` and set `X-Forwarded-For`.

## On your iPhone

Open the Companion in Safari, tap **Share → Add to Home Screen**, then open
it from the Home Screen and sign in once. It then runs full screen, with no
Safari toolbar, and the section tabs sit in the header.

- **Pages open at once.** The phone keeps a saved copy of each page and
  shows it straight away. Until the fresh one arrives, a note at the bottom
  says *Saved 9:42 · checking for updates…*. The page then swaps itself in,
  or offers *Newer numbers ready · tap to show* if you're scrolling or typing.
- **Right after you log something**, pages come from the server, so you see
  your entry.
- **Signing out deletes the saved copies.** So does an expired session.

## Logging from Shortcuts, NFC tags and scripts

**Every API route, with its token scope, body and reply, is in
[`docs/api.md`](docs/api.md)** (rule R18). In short:

Every tracker has its own endpoint, `POST /api/log/<key>`. Its **Connect**
page creates a token that can log only that tracker, so a leaked coffee
token can log coffee and nothing else.

**The easy way:** copy the **Build the Shortcut with a prompt** box from the
Connect page into the Shortcuts app's AI builder. Start every Shortcut's
name with **"Snap a"**: Siri keeps "log a" (Calendar), "record", "add" and
"play" for its own apps. Behind `tailscale serve`, the URL on that page is
`https://`, as it must be.

```bash
curl -X POST -H "Authorization: Bearer hlc_…" -H "Content-Type: application/json" \
  -d '{"value": 2}' https://<host>:8443/api/log/coffee
# {"tracker": "coffee", "value": 2.0, "day": "2026-10-17", "created": true, "message": "Logged Coffee at 07:10", …}
```

- `value` is per type and optional for counts and amounts (1), yes/no
  (yes), moments and time-of-day trackers.
- Entries are stamped when they arrive. Send `time` (ISO 8601 with an
  offset) only to back-date one; more than 5 minutes in the future is
  refused.
- `client_id` (a UUID) makes a retry safe: the same id twice logs once.
- A Shortcut can speak the reply's `message`, so a misheard entry is caught
  right away.
- `GET /api/trackers` (a `read` token) lists trackers.
- `POST /api/log/day_rating` logs tonight's day rating without any setup. The
  next-morning look back is about the day before, so it's logged on the pages.
- `DELETE /api/entries/<client_id>` (scope `all`) removes an entry.

**Missing is not zero.** An unlogged count or yes/no tracker counts as 0
only on a day you marked reviewed, or every day for a tracker you mark "I log
this every time". On other days it stays unknown, so a forgotten entry never
looks like "none" to the analysis.

## API tokens

Shortcuts can't do interactive sign-in, so they use tokens. Each token has
one scope: `all`, `read`, or `log:<tracker_key>` (logs a single tracker only,
from M4). Tokens are shown once and stored hashed.

```bash
docker exec healthlog-companion companion token create "iPhone" --scope read
docker exec healthlog-companion companion token list
docker exec healthlog-companion companion token revoke 3

curl -H "Authorization: Bearer hlc_…" https://<host>:8443/api/today
```

## CLI

| Command | What it does |
|---|---|
| `companion check-upstream` | verify every HealthLog table and column we read; exit 1 on a problem |
| `companion migrate` | apply the Companion's migrations (schema `companion`) |
| `companion set-password [--stdin]` | set the operator password (signs out all sessions) |
| `companion token create NAME --scope …` / `list` / `revoke ID` | manage API tokens |
| `companion push keys` | print a new VAPID key pair for `.env` (reminders) |
| `companion import-days [--apply]` | bring in another app's day-by-day tags, trackers and notes from JSON on stdin (format: `app/importer.py`). A dry run unless `--apply`; repeatable, and a day you logged here keeps your entry |
| `companion refresh` | seed metric settings from HealthLog, copy new State of Mind entries, load the weather file, rebuild the daily feature table, run the insight engine (also nightly at 04:15, and *Run it now* on Discovery) |
| `companion web` | migrate, then serve on port 8000 (the `companion-web` service) |
| `companion jobs` | run the scheduler (the `companion-jobs` service) |

## Reminders (optional)

A nudge at 10:00 to look back on yesterday and at 19:00 to rate today (change
the times on the **Reminders** page, linked from *Your day*). A reminder
whose question you've already answered isn't sent.

1. Make a key pair and add it to `.env`, with `PUSH_ENABLED=true`:
   ```bash
   docker exec healthlog-companion companion push keys
   ```
2. Redeploy: `companion/scripts/deploy.sh companion`.
3. On the iPhone, open the **installed** Companion (Home Screen, see *On
   your iPhone*; iOS 16.4 or later), go to **Reminders**, tap **Turn on
   reminders** and allow notifications. **Send a test** checks the whole path.

Reminders reach the phone through its push service (Apple's), so they work
away from home and don't need the phone on your tailnet. The server needs
outbound internet for the courier. Each reminder is encrypted for your phone
before it leaves the Companion (privacy.md).

## Weather (optional)

Weather and air quality for your area come from [Open-Meteo](https://open-meteo.com)
(no account or key). Set `WEATHER_LATITUDE` and `WEATHER_LONGITUDE` in `.env`
and `WEATHER_SINCE` to your first HealthLog day, then restart. The
`companion-collector` container backfills every hour since then on its first
start and refreshes the last ten days each night at 03:40, before the
Companion's 04:15 refresh. To backfill by hand (any range, safe to repeat):

```bash
docker exec healthlog-companion-collector collector backfill --since 2026-07-15
docker exec healthlog-companion companion refresh
```

`collector once` refreshes the recent days now. What is sent and why it's
safe: [`docs/privacy.md`](docs/privacy.md).

## The almanac

Worked out on the server from the date, with nothing fetched: the moon,
public holidays and days until the next one (by `HOLIDAYS_COUNTRY`, or your
time zone's country), plus day length when `WEATHER_LATITUDE` is set (the
latitude alone, rounded to 0.1°). Analysed like every other series.

## Data the Companion needs from Health Auto Export

The Companion reads what HealthLog stores, so each kind of data needs its own
HAE automation feeding HealthLog (see HealthLog's README):

- **Health Metrics** (sleep *summarized*): the basis of almost everything.
- **Workouts**: for the workout-minutes series.
- **State of Mind**: for the mood series. Until HealthLog parses it itself
  (upstream PR #111), the Companion reads it from HealthLog's raw archive.

## Development

Next steps, machine setup and the work queue: [`docs/next-steps.md`](docs/next-steps.md).

With only Docker on the host, from the repository root:

```bash
companion/scripts/test.sh            # ruff + every suite against a throwaway TimescaleDB
```

Or in `companion/` with a virtualenv:

```bash
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
COMPANION_TEST_ADMIN_URL=postgresql+psycopg://healthlog:healthlog@127.0.0.1:5432/companion_test python -m pytest -q
```

The suite needs a TimescaleDB superuser URL whose database name ends in
`_test`. It refuses anything else, because it resets the schema. It runs
HealthLog's own migrations (from `../backend`, or `UPSTREAM_BACKEND_DIR`), then
our bootstrap and migrations, so the contract and permission tests run
against the real upstream schema. Suites: `unit`, `integration`, `contract`,
`security`, `privacy` and `stats` (the engine's validation suite, 20 seeds)
run on every push. The nightly CI job repeats them against upstream's `dev`
branch as an early warning, with `STATS_SEEDS=200`.
