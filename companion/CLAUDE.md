# CLAUDE.md: Companion

Rules for working in `companion/`, for Claude Code and human contributors
alike. These **override** convenience. Every rule is backed by a risk and a
test in [`docs/risks.md`](docs/risks.md). Design:
[`docs/companion-app-design.md`](docs/companion-app-design.md); build order:
[`docs/plan.md`](docs/plan.md).

The repository root `CLAUDE.md` is upstream's and still applies to upstream
code. Don't edit it, because it's upstream-owned (R1).

## What this is

A multi-timeframe health and lifestyle analysis engine built in this fork on
top of HealthLog. HealthLog (upstream, `anym001/healthlog`) is the data
pipeline; the Companion owns its own schema, engine and UI.

## Rules

### Coexistence with upstream

- **R1: Only touch our paths.** On companion branches, change only
  `companion/**`, `compose.companion.yml`, `compose.local.yml`,
  `.github/workflows/companion*.yml` and `.gitignore`. A change HealthLog
  needs goes upstream as its own PR, branched from `upstream/dev`.
- **R2: Never depend on or write upstream database objects.** No views,
  foreign keys, triggers or SQL-body functions referencing schema `public`.
  The `companion` role has `SELECT` only on `public`. Upstream drops and
  rebuilds its objects (migrations 0016, 0020, 0021); a dependency would
  break their upgrades.
- **R3: All upstream reads go through `app/upstream.py`** (the read
  contract), from base tables, never upstream's views. Update the contract
  and `check-upstream` in the same change.

### Data

- **R4: No real personal data in the repository.** The fork is public. Tests
  and docs use synthetic data only: no Health Auto Export files, dumps, real
  entry ids or real logged values.
- **R7: Missing is not zero.** An absent tracker value is 0 only on a
  reviewed day (or for an "always logged" tracker); otherwise it's NaN.
- **R12: Schema changes only through companion Alembic, in schema
  `companion`.** A tracker's type, unit and scale are locked once data
  exists; changes create a successor version.
- **R14: Time is explicit.** Timezone-aware datetimes only (ruff `DTZ`
  rules); the day boundary and `TZ` come from settings, never defaults
  inherited from upstream. Never compute "tomorrow" by adding 24 h (DST).
- **R16: Source policy per metric.** Never sum a metric across overlapping
  sources; prefer the merged stream, else an explicit priority list.
- **The event log is the source of truth.** Derived tables must be
  rebuildable from it; deletes are tombstones; privacy deletion is `purge`
  (redaction), not row deletion.

### Privacy and security

- **R5: No hidden network calls.** At runtime, the only outbound requests
  are opt-in, allowlisted, fetch-only outside-data sources. Models are baked
  into the image (`HF_HUB_OFFLINE=1`). No telemetry.
- **R6: Capture is structured.** No language model in any capture path.
  Values come from typed inputs; unparseable text becomes a note, never a
  guess.
- **R11: Secrets stay secret.** Secrets come from the environment, never
  YAML or the repo. Tokens and passwords are stored hashed and are never
  logged. Diary text is never logged and is excluded from LLM prompts unless
  the operator opts in.
- **Every state-changing web request is CSRF-protected; every template
  autoescapes; identity headers are trusted only from `TRUSTED_PROXIES`.**

### Analysis

- **R8: No method ships without its validation suite.** It must find
  planted effects, stay within its false-discovery target on null
  (including autocorrelated) data, and reject planted confounders. The FDR
  family covers all features × lags × horizons; one distributed lag model
  counts as one test.
- **R9: Predictive models use time-ordered validation only**, must beat a
  naive baseline to be reported, and never see features from after the
  target.
- **R10: Association language only.** Insight text never says *causes,
  because, leads to* or anything diagnostic. Health-relevant insights may
  suggest discussing with a clinician.
- **R13: Every user-facing number carries its evidence**: *n*, strength,
  and, for text-derived features, the entries behind it.

## Conventions (same as upstream)

English everywhere; ruff (line length 120, plus `DTZ` for the companion);
pytest against a real TimescaleDB; Alembic-only schema; feature branches
merged into the fork's `main`; docs updated in the same change.

## Commands

Handoff, setup and the work queue: [`docs/next-steps.md`](docs/next-steps.md).

- Everything, with only Docker on the host (from the repo root):
  `companion/scripts/test.sh [pytest args]`. It starts the throwaway
  `healthlog-testdb` on 127.0.0.1:55432; `STATS_SEEDS=200` runs the engine's
  validation suite at full strength.
- In a venv (in `companion/`): `ruff check . && ruff format --check .`, then
  `COMPANION_TEST_ADMIN_URL=postgresql+psycopg://healthlog:healthlog@127.0.0.1:55432/companion_test python -m pytest -q`.
  The database name must end in `_test`: the suite resets schemas. Never
  point it at the live database.
- Path allowlist (R1): `sh companion/scripts/check_paths.sh upstream/dev`
- Upstream contract (live): `docker exec healthlog-companion companion check-upstream`
- Rebuild features and insights (live): `docker exec healthlog-companion companion refresh`
