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
| A1 | **State of Mind parsing** (`data.stateOfMind` → table, re-derive from `raw_ingest`) | **merged** (#111, 2026-10-18); maintainer follow-ups #112 (Grafana "Mood (State of Mind)" row, backfill counts). On `dev`, not yet in a release |
| A2 | **Registry entries** for lifestyle metrics: caffeine, alcohol, water, mindful minutes … (units, bounds, aggregation; which are `core` is discussed in the PR) | requested on #107 |
| A5 | **Symptoms and Medications**: in HAE these are their own data types (`data.symptoms`, `data.medications`), not Health Metrics, so they need their own parser and table like State of Mind, not registry entries (maintainer, #111) | **low priority**: we track neither today. Symptoms first, medications second (after a real iOS 26 sample). Shape proposed on #111 (2026-10-18); draft in [`next-steps.md`](next-steps.md) §4.1 |
| A3 | **Time zone fix**: `daily_metrics` view and Grafana dashboards hard-code `Europe/Vienna` regardless of `TZ`; add a `TZ`-mismatch warning to `healthlog audit` (risks.md L1b) | **merged** (#108; maintainer follow-ups #109, #110) |
| A4 | Ingest/parser bugs found along the way | as found; next: **unaggregated sleep is dropped** (risks.md L3) |

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
| B0 | **Housekeeping** | **done** (2026-10-17): Grafana in `compose.local.yml`, docs and `.gitignore` on the fork's `main`. Still open: a project name |
| B1 | **Skeleton** | **built** (M1, 2026-10-17): `companion/` app + compose override; own schema/role (read-only on HealthLog); own Alembic; read contract + startup check; `password` auth + scoped API tokens; a **Today** page that shows HealthLog data as sentences. Running locally; HTTPS front end still to set up |
| B2 | **More Health metrics** | **built** (M2, 2026-10-17): read *every* metric HealthLog stores, not just its 19 `core` ones; our own per-metric settings (aggregation, bounds, source priority, which to analyse), editable on the Metrics page; State of Mind straight from `raw_ingest` until A1 lands; the daily feature table B5 builds on |
| B3 | **Custom tracking beyond Health** | **part 1 live** (M4, 2026-10-17): typed trackers as data, created in the web app; observations + event log; per-tracker URLs and scoped tokens; quick-add + evening review, feeding the analysis. Simpler setup (2026-10-18): a Trackers page of your trackers, today's tags and a short form with ideas that fill it in, name + kind only, ratings fixed at 1–10 and coloured low → high, **day tags** (each a daily 0/1 series), no "higher is better" setting. Part 2: the generic **Track** Shortcut (menus, automatic time, no free-text guessing), Apple Health "Log Health Sample" recipes, PWA offline queue, spans |
| B4 | **Outside data sources** | **weather** first (temperature, humidity, barometric pressure and its change, precipitation, cloud cover, UV, air quality), then calendar busyness, public holidays, sunrise/sunset and daylight. Opt-in, coarse location, fetch-only (design §2.5) |
| B5 | **Analysis engine (multi-timeframe)** | **v1 live** (M5, 2026-10-17): one feature table over all sources; horizons **day** (lags 0–1, both directions), **week/month** (change detection), weekday rhythm; one FDR family, validated on synthetic data. Still to come: lags 2–7 via distributed lag models, **season** (long trends), **within-day** (event-locked responses, e.g. coffee → steps over the next hours) |
| B6 | **ML models** | next-day prediction (mood, productivity, sleep, HRV) with feature importance as "what drives X"; day-type clustering; change-point detection; multivariate anomalies (design §4.7) |
| B7 | **Diary** | quick entries, local embeddings (pgvector), user concepts + discovered themes as features, with evidence shown |
| B8 | **Experiments** | n-of-1 interventions with baselines and confounder checks |
| B9 | **Imports & interop** | CSV import from other tracking apps (to run alongside them and bring their history in); export of our data |
| B11 | **Look and layout** | **Modernist look adopted** (2026-10-18): Archivo, ink on light ground, one red accent, 2px rules, bottom tabs on phones, coverage strip, provenance and Preliminary tags ([`design.md`](design.md)). Still from the wireframes: Explore, Experiments, Settings and data, evidence intervals. **Direction open:** wireframes PDF shared with the maintainer on #107 (2026-10-18); Joe leans towards a warmer, organic skin (browns, greens, softer type), so the look may change before more screens are built. Reference for tone: WaterLlama (friendly, a non-threatening mascot) |
| B10 | **Polish** | reminders (web push), insight ranking, weekly summary, optional native iOS app (App Intents) later |

Dependencies: B1 first. After that, B2, B3 and B4 are independent input
streams and can be built side by side. B5 starts as soon as any one of them
produces data, and grows as each lands. B6 needs B5's feature table and a few
months of data. B7–B10 can happen in any order.

## Next steps

**Done** (as of 2026-10-18):
- B0, B1 (M1), B2 (M2), B3 part 1 (M4), B5 v1 (M5).
- A0, A1 (#111) and A3 merged upstream.

The detailed handoff is [`next-steps.md`](next-steps.md): operator to-dos,
machine setup, the work queue, and lessons learned. In short:

1. **Unblock the data (no code).**
   - Set the Companion password and put HTTPS in front.
   - Re-import the sleep history summarized (risks.md L3).
   - Add the Workouts and State of Mind automations in HAE.
   - Create trackers. Until these land, the engine has too few overlapping
     days to report anything.
2. **Upstream:** a small A4 PR so dropped sleep segments are counted, not
   silent; A2 registry entries. A5 (symptoms, then medications) is low
   priority; its shape is proposed on #111.
   Switch mood to `public.state_of_mind` once a release ships it.
3. **B4 (M3) weather:** backfills the whole history, so it gives the engine
   data right away. It brings the first allowlisted outbound call (R5).
4. **B3 part 2 (M4):** the Track Shortcut (with day tags), offline PWA, spans.
5. **Design (B11):** collect feedback on the review page
   ([`design.md`](design.md)); next from the wireframes are evidence
   intervals (they need CIs from the engine), then Explore (3a).
6. **B5 follow-ups:**
   - distributed lag models
   - adjusted re-checks
   - **M6** within-day effects (coffee → steps over the next hours)

## Keeping in sync

- `git fetch upstream && git merge upstream/main` into the fork after each
  upstream release.
- After each sync: rebuild, run our startup contract check, run `backup.sh`.
- Upstream PRs: branch from `upstream/dev`, one topic per PR, their
  conventions (`CONTRIBUTING.md`).
