# Development plan

The concrete build plan for the Companion: milestones, tasks, and a
"done when" test for each. **Picking this up again?** Start with
[`next-steps.md`](next-steps.md) (state, setup, work queue). Strategy lives in [`roadmap.md`](roadmap.md),
design in [`companion-app-design.md`](companion-app-design.md); this file is
what we actually work through.

## Guiding sequence: start the data clock early

Most insights need **weeks to months of data**, so the order is driven by one
idea: **start collecting as early as possible, and build analysis while the
data accumulates.**

1. Things that need no new data come first, as quick wins: HealthLog already
   holds ~3 months of history (since 2026-07-16), and weather history can be
   backfilled for that whole period.
2. Capture (trackers, Shortcut) comes early, so self-tracked data starts
   accruing while the engine is built.
3. Heavier analysis (lag models, ML) comes once there's enough data for it to
   say anything.

## Defaults (changeable, chosen so work can start)

| Decision | Default | Why |
|---|---|---|
| Stack | Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, pandas/scipy/statsmodels | same as upstream: one toolset, easy PRs |
| Front end | server-rendered Jinja + HTMX, a small service worker, no build step | forms and cards don't need a SPA |
| Processes | one image, two compose services: `companion-web` (uvicorn) and `companion-jobs` (APScheduler) | mirrors upstream's web/analysis split |
| Day boundary | 04:00 local | late nights count as the same day |
| Outside data | fetch-only, Open-Meteo, coarse home location | key-less, has historical backfill |
| Embeddings | small model inside the companion container | diary text stays on the server |
| Auth | `password` mode + scoped API tokens; `proxy_header` mode later | works behind any proxy |
| Name | "Companion" | placeholder |

## Working agreement

- One branch per milestone (`feature/companion-m1-skeleton`, …), merged into
  the fork's `main`. Upstream work branches from `upstream/dev` as before.
- Every milestone ends with: lint (ruff), tests (pytest against a real
  TimescaleDB), a rebuild, and a short note in the docs.
- Analysis math is DB-free and tested against synthetic data with a
  **planted effect** and a fixed seed (upstream's convention): if the engine
  can't find an effect we planted, it doesn't ship.
- After each upstream sync: rebuild, run `companion check-upstream`, run `backup.sh`.

---

## M0: Housekeeping (small, now)

- [x] Move the Grafana service from `docker-compose.yml` to `compose.local.yml`; restore upstream's file.
- [x] Start logging Apple **State of Mind** on the Watch / iPhone (no code). (28 entries by 2026-10-14.)
- [x] Push this branch to the public fork (see the note at the end).
- [x] Fix HealthLog's time zone (risks.md L1): `TZ=America/New_York` in `.env`, recreate the container. (Done: the live container runs New York time.)
- [ ] Re-run `analyze`, `rederive-stress` and `rederive-body-battery` after the TZ change (not verified).

**Done when:** `git status` shows upstream files untouched; State of Mind entries appear in tonight's sync.

## A1: State of Mind PR to upstream (small, in parallel with M1)

- [x] Parser for `data.stateOfMind` → new table (`hae_id` UUID key, time, kind, valence, classification, labels[], associations[]).
- [x] Alembic migration; a `rederive-state-of-mind` command modelled on `rederive-workout-hr`.
- [x] Tests (parser, idempotency, re-derive); README + ARCHITECTURE updates in the same PR.
- [x] PR against `dev`: [#111](https://github.com/anym001/healthlog/pull/111) (2026-10-17). It also fixes ISO-8601 timestamps, which the parser rejected, and asks the maintainer how he'd like it shown in Grafana.

**Done when:** the PR is open with green checks. Merged 2026-10-18; until a release ships it, M2 reads State of Mind straight from `raw_ingest`.

## M1: Skeleton (medium)

The goal is to prove the isolation model and the auth end to end, with one
useful page.

- [x] `companion/` package: `app/` (FastAPI), `migrations/`, `web/` (templates, static), `tests/`, `Dockerfile`, `pyproject.toml`, `requirements*.txt`. (The service worker moves to M4, with the PWA.)
- [x] `compose.companion.yml`: `companion-web` + `companion-jobs`, same DB host, own env vars.
- [x] **DB bootstrap script** (`bootstrap/bootstrap.sql`, run once as the DB superuser): role `companion`, schema `companion`, `SELECT` on HealthLog's tables (and default privileges for future ones), `CREATE EXTENSION vector SCHEMA companion`.
- [x] Alembic with `version_table_schema="companion"`; first migration: `users` (single user), `sessions`, `api_tokens`, `settings`.
- [x] **Read contract** module (`app/upstream.py`): every HealthLog table/column we read, in one place. `companion check-upstream` CLI + check at startup + nightly (04:10).
- [x] Auth: hashed password (argon2) → session cookie (`HttpOnly`, `Secure`, `SameSite=Strict`) + CSRF token on forms + lockout; API tokens (hashed, scoped, revocable). `TRUSTED_PROXIES` handling like upstream.
- [x] **Today** page: last night's sleep and yesterday's HRV, resting HR, steps, stress, energy reserve as sentences against personal baselines, each with its *n*. Also `GET /api/today`.
- [x] CI workflow `.github/workflows/companion.yml`: path check + ruff (with `DTZ`) + the fast test suites (unit, integration, contract, security, privacy) + image build; `companion-nightly.yml` runs the suite against upstream's `dev` migrations (the stats suite joins in M5).
- [x] Guard tests from day one: no dependencies on `public` (A1), role can't write `public` (A5), future tables readable (A4), contract reads only in `upstream.py` (A3), path allowlist (A6), repo scan for personal data (E1), egress block (E2).
- [x] Docs: [`../README.md`](../README.md) (install/run, Tailscale Serve recipe), [`architecture.md`](architecture.md), [`privacy.md`](privacy.md).
- [ ] Operator steps: set the password (`companion set-password`) and put HTTPS in front (Tailscale Serve), then sign in from the phone.

**Done when:**
- [x] `docker compose -f docker-compose.yml -f compose.companion.yml up -d` starts it (live since 2026-10-17, with `compose.local.yml` too);
- [ ] login works (covered by tests; waits on the operator password and HTTPS); [x] the Today page shows real sentences (checked live via `/api/today`);
- [x] a test proves the `companion` role **cannot** write to HealthLog's tables;
- [x] `check-upstream` passes against the live database (5 tables).

## M2: Health data coverage (small–medium)

- [x] `metric_settings` in our schema: per-metric aggregation, bounds, source priority, "analyse" flag. Seeded from upstream's registry, then *ours* to edit (on the Metrics page), so all 41 metrics can be analysed, not just the 19 `core` ones.
- [x] Daily loader from **base tables** (`metric_samples`, `sleep_sessions`, `stress_intraday`, `body_battery_intraday`, `workouts`), with our day boundary and time zone. Never upstream's views. Results go to the **daily feature table** (`daily_features` + `feature_defs`, pulled forward from M5), rebuilt by `companion refresh` and nightly at 04:15.
- [x] State of Mind reader from `raw_ingest` with a cursor (deduplicated by entry id), until A1 lands → `mood_entries`.
- [x] A **Metrics** page: each series' last 30 days vs the 30 before, weekday profile, 60-day sparkline, per-metric settings. Today gains a mood line.

**Done when:** every metric HealthLog stores appears as a daily series with correct aggregation; State of Mind appears as daily valence plus emotion/association counts.
**Status (2026-10-17):** done. Live: 76 features, 1,834 day values (31 HealthLog metrics, 5 sleep, stress, energy, 37 mood), 30 State of Mind entries. Data gaps found: no Workouts automation (0 workouts in HealthLog), no State of Mind automation (the last entry arrived with a manual export on Oct 16), and sleep history is missing (risks.md L3).

## M3: Outside data, part 1: weather (small–medium; the first quick win)

Weather history can be backfilled, so this delivers insights on existing
data immediately.

- [ ] Opt-in config: coarse home location (rounded to ~10 km), sources on/off.
- [ ] Open-Meteo client: daily + hourly weather (temperature, humidity, pressure, precipitation, cloud, wind, UV) and air quality; **historical backfill** for all HealthLog days; nightly incremental fetch; `source_cache` table.
- [ ] Computed locally: sunrise/sunset/day length (`astral`), public holidays (`holidays`).
- [ ] A first simple insight pass on existing data: same-day and next-day associations between weather and sleep, HRV, steps, stress.

**Done when:** weather features exist for every day since 2026-07-16; the Today page mentions relevant weather ("pressure dropped 9 hPa since yesterday"); a few weather associations appear (with *n* and honest strength).

## M4: Trackers & capture (large; starts the self-tracking clock)

- [x] Tables: `trackers`, `events` (append-only), `observations`, `day_reviews`. *(`spans` for vacation, sick, travel: part 2.)*
- [x] Type system (§2.1 of the design): validation, input widgets and daily-feature derivation per type, including time-of-day features (minutes after midnight, rolled past the day boundary). *(Minutes after waking: once sleep history is complete, risks.md L3.)*
- [x] API: `POST /api/log/{tracker_key}` (idempotent on `client_id`), `GET /api/trackers`, `DELETE /api/entries/{id}` (tombstone). Tracker create/edit/version in the web app; type, unit and scale locked once data exists, with successor versions (R12).
- [x] Per-tracker scoped tokens + the **Set up** panel (URL, body, shown-once token, curl line, Siri notes). *(Test link: with the Shortcut.)*
- [x] Web: Today quick-add (pinned trackers, one tap), **evening review** (generated from tracker types, marks the day reviewed), back-dating, entry delete. *(Offline queue, service worker and installable manifest: part 2.)*
- [ ] **Generic Track Shortcut**: built once by hand on an iPhone (it can't be generated by code), shared via iCloud link with import questions; documented one-word stubs.
- [ ] Docs: Apple Health **"Log Health Sample"** recipes for caffeine, alcohol, water, symptoms (symptoms reach HealthLog once A5 lands).
- [x] Trackers page in three bounded panels (2026-10-18): **What you track** (plain words: "Rating, 1 low to 10 high", "How many pages"), **Day tags** (pick today's, add your own or tap a suggestion, remove), **New tracker** (name + kind, ideas that fill the form). Nothing overlapping Apple Health is suggested. "Higher is better" is gone everywhere; every active tracker is in Quick add and the daily log.
- [x] **The number, not the entries** (2026-10-19): Quick add and the daily log show each tracker's day value (total with − / +, or the chosen rating), no time fields, no "Logged today" list. History is folded away on the tracker's page; Shortcut/token setup is its own page.
- [x] **Day tags**: tags belong to the day, not to a tracker. They start empty: one box finds an existing tag (the browser suggests as you type) or adds a new one, and picks it for the day; tiles toggle; "Edit list" removes for good. Tap on and off on Overview ("Today was…") and the daily log; each tag becomes a daily 0/1 feature (2026-10-18).
- [x] Simpler New metric form: name, kind, and only the detail that kind needs; ratings are always 1–10, coloured low → high instead of labelled (2026-10-18).

**Done when:** from the Watch, "Hey Siri, track" → Coffee is logged in under 5 seconds; a custom productivity scale is filled in the evening review; deleting an entry survives a full re-derive from the event log.
**Status (2026-10-17):** part 1 live. The review, the scale and the delete-survives-rebuild criteria are met; the 5-second Siri log waits on the hand-built Shortcut (part 2). Live smoke test: a log-only token logs its tracker in local time, gets 403 on another tracker and 422 on an invalid value.

## M5: Analysis engine v1 (large)

- [ ] **Feature table builder**: one row per day, columns from HealthLog, State of Mind, trackers, weather; the reviewed-day rule (missing ≠ zero). *(The table and the HealthLog + mood columns exist since M2; trackers and weather add columns.)*
- [x] Day-level relationships with lags (Spearman on residuals; Mann-Whitney/Cliff's delta; Fisher), FDR, effect floors, minimum support. Lags 0 and +1 in both directions; families keep definitional pairs out.
- [ ] **Distributed lag models** for daily exposures (weather, sleep, caffeine) → outcome curves over lags 0–7 ("rain Monday → mood Wednesday"). *(Needs months of data; next.)*
- [x] Week/month views: last 7 vs 28 days and last 28 vs 56 days, as autocorrelation-aware mean shifts.
- [x] Descriptive insights: weekday rhythms (Kruskal-Wallis); 30-day vs prior on the Metrics page. *(Streaks and bests: later.)*
- [x] Likely ranges (95%, effective-n aware) on every association and change, with coverage checks (2026-10-19).
- [x] Sentence templates per method and type; **Insights** feed with an "explain" view (numbers, method, *n*, evidence); `GET /api/insights`.
- [x] Nightly job at 04:15 (after HealthLog's 03:30 run), at the end of the refresh.
- [x] Synthetic validation suite: planted same-day, lagged and yes/no effects found; weekday and trend confounders rejected; null calibration on autocorrelated noise. *(Curved effects come with the distributed lag models.)* It caught two miscalibrated tests before release ([`analysis-engine.md`](analysis-engine.md)).

**Status (2026-10-17):** v1 done and live. The first real run tested 701 patterns over 26 of 76 series and reported none, correctly so: too few overlapping days (see analysis-engine.md).

**Done when:** the validation suite passes, and the Insights feed shows ranked, explained insights on real data, each with *n* and strength.

## Design and hardening (2026-10-19)

- [x] Warm look live (`warm.css` over `style.css`; Modernist one `<link>` away).
- [x] At a glance: Overview tiles, discovery heads, inline icons (`app/glance.py`).
- [x] Day tags in eight fixed colours, by list position.
- [x] Web port bound to `127.0.0.1`.
- [ ] Glance treatment on Metrics and the evidence page.
- [ ] Boundary checks in CI: route sweep, no-network container, one port, database role, extensions (roadmap B12).
- [ ] Grant `SELECT` on the contract tables only.
- [x] Deploy, rehearsal and rollback scripts; restore and upgrade tested on a copy of real data ([`upgrading.md`](upgrading.md)).
- [ ] Pin the HealthLog image; nightly contract check against `:dev`.

## M6 and later (ordered by what the data asks for)

| Milestone | Scope (design ref.) | Needs |
|---|---|---|
| M6 Within-day effects | event-locked responses, e.g. coffee → steps/HR/stress over the next hours, vs time-matched baselines (§4.3) | M4 events + minute-level data |
| M7 ML models | next-day prediction with feature importance, day types, change points, multivariate anomalies; time-ordered CV; must beat a naive baseline (§4.7) | M5 feature table + ~90 days |
| M8 Diary | entries, embeddings (pgvector), concepts with confirm/reject tuning, themes, evidence views (§3) | M5 |
| M9 Experiments | n-of-1 interventions with baselines and confounder checks (§4.5) | M5 |
| M10 Imports & interop | CSV import from other tracking apps; export (§5) | M4 |
| M11 Polish | reminders (web push), weekly summary, `proxy_header` auth, optional native iOS app | — |

Throughout: anything generic about getting Apple Health data in becomes an
upstream PR (A2 registry entries is the next one, informed by M2; Symptoms
and Medications are their own data types upstream, A5).

## Docs expansion (alongside the milestones)

Split the design document into focused docs as each area gets built:

| Doc | Written with |
|---|---|
| `vision.md`: the questions the product answers, and for whom | before M1 |
| `architecture.md`: isolation, auth, upstream sync, deployment | M1 |
| `data-and-capture.md`: trackers, Apple Health, Shortcuts, outside sources | M3–M4 |
| `analysis-engine.md`: horizons, lag models, within-day, ML, guardrails | M5–M7 |
| `privacy.md`: what stays local, what's fetched, what's sent to models | M1, updated each milestone |

## Risks and rules

The full register (live findings, coupling, data correctness, statistics,
security, privacy, operations) with a mitigation and a test for each is in
[`risks.md`](risks.md). The binding rules that follow from it are in
[`../CLAUDE.md`](../CLAUDE.md). Two items affect the running system today
(risks.md §0): HealthLog's time zone is Vienna instead of US Eastern, and
heart rate arrives from overlapping sources.

## Note on publishing

The fork is **public**. These docs contain no personal data: State of Mind
examples are illustrative, and example trackers are deliberately generic
(coffee, productivity, first social-media use). Keep it that way (rule R4).
