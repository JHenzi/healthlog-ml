# Roadmap

**The fork is the product.** We build our own health and lifestyle analysis
engine in this fork, at our own pace, and in parallel offer upstream
whatever fits HealthLog's scope. There's no separate repository: the
companion lives in `companion/` inside the fork. Design:
[`companion-app-design.md`](companion-app-design.md). Build plan
(milestones, tasks, "done when" tests): [`plan.md`](plan.md).

## How we work

- **Parallel tracks.** Upstream PRs and our own building run at the same
  time; neither waits for the other.
- **A light fork by default.** Our code lives in `companion/` and its own
  database schema; upstream's `backend/` stays untouched, so upstream
  releases keep merging cleanly and their fixes flow to us for free. When we
  *need* to change `backend/`, we do it, and if the change is useful upstream
  we also send it as a PR so it comes back to us through their releases.
  If the directions drift too far apart, we can stop syncing at any point.
- **Iterate fast.** Build a slice, use it on real data, look at what it
  tells us, and adjust. After each slice ask: *did we hit something generic
  in HealthLog?* If yes, it's an upstream item.

## Track A: upstream contributions

Rule of thumb: **getting Apple Health data in correctly is upstream; what the
data means is ours.**

| # | Item | Status |
|---|---|---|
| A0 | Large-backfill split fix | **merged** (#104; maintainer follow-up #105) |
| A1 | **State of Mind parsing** (`data.stateOfMind` → table, re-derive from `raw_ingest`) | requested by the maintainer on #107 |
| A2 | **Registry entries** for lifestyle metrics: caffeine, alcohol, water, symptoms, mindful minutes … (units, bounds, aggregation; which are `core` is discussed in the PR) | requested on #107 |
| A3 | **Time zone fix**: `daily_metrics` view and Grafana dashboards hard-code `Europe/Vienna` regardless of `TZ`; add a `TZ`-mismatch warning to `healthlog audit` (risks.md L1b) | **PR #108 open** |
| A4 | Ingest/parser bugs found along the way | as found |

For reference, the maintainer's suggested order on
[#107](https://github.com/anym001/healthlog/issues/107) (State of Mind →
registry → entries/API design doc → entries & API → separate frontend →
within-day effects) is a map of **what HealthLog itself lacks** for manual
data: nowhere to store it, no read API, no auth for apps, daily-grid-only
analysis. We solve those gaps in our own layer instead of waiting for them
upstream; if he later builds an entries API, we can adopt it then.

## Track B: our product

Several streams can run in parallel once B1 exists:

| # | Stream | What |
|---|---|---|
| B0 | **Housekeeping** | move the Grafana service out of upstream's `docker-compose.yml` into our compose override; commit `.gitignore` and the docs to the fork; pick a project name |
| B1 | **Skeleton** | `companion/` app + compose override; own schema/role (read-only on HealthLog); own Alembic; read contract + startup check; `password` auth + scoped API tokens; a **Today** page that shows HealthLog data as sentences |
| B2 | **More Health metrics** | read *every* metric HealthLog stores, not just its 19 `core` ones; our own per-metric settings (aggregation, bounds, which to analyse) in our schema; State of Mind straight from `raw_ingest` until A1 lands |
| B3 | **Custom tracking beyond Health** | typed trackers as data; observations + event log; per-tracker URLs and scoped tokens; the generic **Track** Shortcut (menus, automatic time, no free-text guessing); Apple Health "Log Health Sample" recipes for what Health can model; PWA quick-add + evening review |
| B4 | **Outside data sources** | **weather** first (temperature, humidity, barometric pressure and its change, precipitation, cloud cover, UV, air quality), then calendar busyness, public holidays, sunrise/sunset and daylight. Opt-in, coarse location, fetch-only (design §2.5) |
| B5 | **Analysis engine (multi-timeframe)** | one feature table over all sources; horizons **day** (lags 0–3), **week/month** (rolling comparisons, change detection), **season** (long trends), **within-day** (event-locked responses, e.g. coffee → steps over the next hours); sentences with *n*, strength and direction |
| B6 | **ML models** | next-day prediction (mood, productivity, sleep, HRV) with feature importance as "what drives X"; day-type clustering; change-point detection; multivariate anomalies (design §4.7) |
| B7 | **Diary** | quick entries, local embeddings (pgvector), user concepts + discovered themes as features, with evidence shown |
| B8 | **Experiments** | n-of-1 interventions with baselines and confounder checks |
| B9 | **Imports & interop** | CSV import from other tracking apps (to run alongside them and bring their history in); export of our data |
| B10 | **Polish** | reminders (web push), insight ranking, weekly summary, optional native iOS app (App Intents) later |

Dependencies: B1 first. After that, B2, B3 and B4 are independent input
streams and can be built side by side. B5 starts as soon as any one of them
produces data, and grows as each lands. B6 needs B5's feature table and a few
months of data. B7–B10 can happen in any order.

## Next steps

1. **Reply on #107**: thanks; we'll send A1 + A2; the analysis engine and UI
   will be built in our fork, beyond HealthLog's scope, with ingest-level
   fixes sent upstream as we find them.
2. **Start logging State of Mind** on the Watch (costs nothing; data
   accumulates for B5).
3. **B0 → B1**, and **A1** in parallel.
4. Then B2 / B3 / B4 side by side, B5 as data arrives.

## Keeping in sync

- `git fetch upstream && git merge upstream/main` into the fork after each
  upstream release.
- After each sync: rebuild, run our startup contract check, run `backup.sh`.
- Upstream PRs: branch from `upstream/dev`, one topic per PR, their
  conventions (`CONTRIBUTING.md`).
