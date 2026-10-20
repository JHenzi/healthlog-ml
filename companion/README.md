# HealthLog Companion

Our analysis engine and UI on top of [HealthLog](../README.md). HealthLog is
the data pipeline (Apple Health → TimescaleDB). The Companion reads its tables
**read-only**, keeps its own data in schema `companion`, and turns it into
plain-language sentences. Design: [`docs/companion-app-design.md`](docs/companion-app-design.md).
Rules: [`CLAUDE.md`](CLAUDE.md). Build plan: [`docs/plan.md`](docs/plan.md).

What works today (milestones M1, M2, M4 part 1 and M5 v1):

- a **Today** page: last night's sleep and yesterday's HRV, resting heart
  rate, steps, stress, energy reserve and mood, each against your 30-day
  average, with the number of days behind that average;
- a **Metrics** page: every daily series the Companion builds (all of
  HealthLog's metrics, sleep stages, stress, energy reserve, workouts and
  Apple Health State of Mind), each with its last 30 days against the 30
  before, a weekday profile and a 60-day sparkline. For HealthLog metrics you
  can change how a day's value is formed (sum, average, lowest, highest),
  which sources to prefer, plausibility bounds, and whether it's analysed;
- an **Insights** page: relationships between series (same day and next day,
  in both directions), changes over the last week and month, and weekday
  rhythms. Each finding is a sentence with its number of days and strength,
  plus an *explain* view with the method and statistics. False discoveries
  are held to 10%, and the engine is validated on synthetic data before it
  ships ([`docs/analysis-engine.md`](docs/analysis-engine.md));
- `GET /api/insights` (a `read` token);
- **your own trackers**: create anything you want to track (a count like
  coffee, a 1–5 productivity scale, yes/no, an amount with a unit, a
  duration, a time of day, a choice such as lunch at home / takeout /
  skipped, or a moment like anger with an intensity). Log with one tap on
  Today, back-date from the tracker's page, and fill gaps in the **evening
  review**. Every tracker becomes daily series in the same analysis;
- password sign-in, plus scoped API tokens for Shortcuts and scripts;
- `GET /api/today` (a `read` token), the same sentences as JSON, plus `notes` (a weather change, streaks, records);
- a startup and nightly check that HealthLog's tables still match what we
  read (`companion check-upstream`).

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

## Logging from Shortcuts, NFC tags and scripts

Every tracker has its own endpoint, `POST /api/log/<key>`. Its **Set up**
panel creates a token that can log only that tracker, so a leaked coffee
token can log coffee and nothing else.

```bash
curl -X POST -H "Authorization: Bearer hlc_…" -H "Content-Type: application/json" \
  -d '{"value": 2}' https://<host>:8443/api/log/coffee
# {"tracker": "coffee", "value": 2.0, "day": "2026-10-17", "created": true, "message": "Logged Coffee at 07:10", …}
```

- `value` is per type and optional for counts (1), yes/no (yes), moments and
  time-of-day trackers.
- `time` (ISO 8601 with an offset) back-dates an entry. More than 5 minutes
  in the future is refused.
- `client_id` (a UUID) makes a retry safe: the same id twice logs once.
- A Shortcut can speak the reply's `message`, so a misheard entry is caught
  right away.
- `GET /api/trackers` (a `read` token) lists trackers.
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
| `companion refresh` | seed metric settings from HealthLog, copy new State of Mind entries, load the weather file, rebuild the daily feature table, run the insight engine (also nightly at 04:15, and *Rebuild now* on the Metrics and Insights pages) |
| `companion web` | migrate, then serve on port 8000 (the `companion-web` service) |
| `companion jobs` | run the scheduler (the `companion-jobs` service) |

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
