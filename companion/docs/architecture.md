# Architecture

How the Companion sits next to HealthLog without breaking it. The full design
is in [`companion-app-design.md`](companion-app-design.md) §8. This file
describes what is built (M1).

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
`companion-jobs` runs scheduled work: today only the 04:10 contract check,
later the nightly analysis (M5, at 04:15, after HealthLog's 03:30 run). The
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
`stress_intraday`, `body_battery_intraday`. We read the intraday stress and
energy tables rather than HealthLog's `*_daily` tables because those use
midnight days. Ours use the day boundary.

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
