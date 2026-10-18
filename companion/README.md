# HealthLog Companion

Our analysis engine and UI on top of [HealthLog](../README.md). HealthLog is
the data pipeline (Apple Health → TimescaleDB). The Companion reads its tables
**read-only**, keeps its own data in schema `companion`, and turns it into
plain-language sentences. Design: [`docs/companion-app-design.md`](docs/companion-app-design.md).
Rules: [`CLAUDE.md`](CLAUDE.md). Build plan: [`docs/plan.md`](docs/plan.md).

What works today (milestone M1):

- a **Today** page: last night's sleep and yesterday's HRV, resting heart
  rate, steps, stress and energy reserve, each against your 30-day average,
  with the number of days behind that average;
- password sign-in, plus scoped API tokens for Shortcuts and scripts;
- `GET /api/today` (a `read` token), the same sentences as JSON;
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
   port `8020` (`COMPANION_PORT`). `companion-jobs` runs scheduled work.

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
| `COMPANION_COOKIE_SECURE` | `true` | send the session cookie over HTTPS only; leave on in production |
| `TRUSTED_PROXIES` | private ranges | same meaning as HealthLog's: which peers may set `X-Forwarded-For` |

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
| `companion web` | migrate, then serve on port 8000 (the `companion-web` service) |
| `companion jobs` | run the scheduler (the `companion-jobs` service) |

## Development

Run in `companion/`:

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
`security` and `privacy` run on every push. The nightly CI job repeats them
against upstream's `dev` branch as an early warning.
