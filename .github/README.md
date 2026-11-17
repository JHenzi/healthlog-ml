<p align="center"><img src="../companion/docs/design/icon.png" width="120" alt="The Companion icon: a light cross on a teal network of points"></p>

<h1 align="center">Health and Discovery Companion</h1>

<p align="center"><b>What goes together in <i>your</i> health data, in plain sentences, on your own server.</b></p>

> [!IMPORTANT]
> **This is a fork. Report bugs and ask questions here, not upstream.**
> Anything you hit while running this repository, including its HealthLog, goes to
> **[this fork's issues](https://github.com/JHenzi/healthlog-ml/issues)**. Please don't file it on
> [anym001/healthlog](https://github.com/anym001/healthlog): its maintainer didn't write the
> Companion and shouldn't have to sort out our changes. If the bug turns out to be in HealthLog itself,
> we reproduce it on plain upstream and report it there ourselves, with a fix when we can.

The Companion brings your Apple Health data together with what you log
yourself and the world outside (weather, daylight, the moon, holidays). It
turns all of it into one number per day per series and compares everything
with everything, in both directions. It then tells you what tends to go
together in **your** data, with the evidence attached:

> *Higher steps tends to be followed by higher sleep (total) over the next
> days, most around 3 days later (80 days, moderate).*

It has no built-in theory of what matters. Only what clears a strict
false-discovery bar is shown, and the wording never claims a cause. Nothing
leaves your machine: no telemetry, no cloud, no model APIs.

<p align="center"><img src="../companion/docs/screenshots/metric-detail-cortisol.png" width="560" alt="A tracker's page in the Companion: Cortisol awakening response level (highest), 37 days of data. A 60-day sparkline, the latest value against the last 30 days and the 30 before, a 30-day calendar with each day coloured low, usual or high for you, and the average per weekday coloured the same way."></p>
<p align="center"><sub>A self-tracked series on its own page: each day coloured by where it falls among your own days, and your weekday pattern.</sub></p>

## What's in it

- **Overview**: rate your day in the evening, then look back blind the next
  morning. Yesterday compared with your usual, a good-day score, and
  Momentum: streaks, records and what's moving.
- **Discovery**: relationships on the same day, the next day or spread over
  the following week. Week and month changes and weekday rhythms, each with
  its number of days, strength, likely range and an evidence page.
- **Capture and Trackers**: measure anything (counts, ratings, times of day,
  day tags, a diary). Log from Siri, an NFC tag or the Action button via
  Shortcuts, or import your history from another tracking app.
- **My Metrics**: every series, readable. Sleep and its timing, HRV, stress,
  energy reserve, workouts, State of Mind, water, weather, and your own
  trackers.
- **Installable on the phone**, with optional push reminders. A documented
  JSON API.

The statistics: residuals after removing weekday profiles and trends,
effective sample sizes for day-to-day carry-over, one Benjamini-Hochberg
family over every test of a run, effect floors, and a validation suite
that plants effects and confounders before any method ships.

**→ [The full Companion README](../companion/README.md)**: features, install,
settings, Shortcuts, API and CLI.

## HealthLog: the foundation, and where we contribute

**None of this exists without [HealthLog](https://github.com/anym001/healthlog)** by
[@anym001](https://github.com/anym001). It is the whole data pipeline: Health Auto Export →
FastAPI ingest → TimescaleDB, idempotent and metric-agnostic. It also has nightly statistics, a stress
and energy-reserve model, Grafana dashboards and optional local narration, all self-hosted with no
outbound calls. It is careful, well-documented work, and the Companion stands entirely on it. If you
only want your Apple Health data in your own database and dashboards, **use HealthLog directly**;
it's excellent.

This fork isn't a split. It follows HealthLog upstream, and we contribute back. Improvements that
belong in the pipeline go upstream first, as their own pull requests, and the fork picks them up from
there. Merged so far:

| Upstream PR | What it added to HealthLog |
|---|---|
| [#104](https://github.com/anym001/healthlog/pull/104) | Split oversized backfill files to fit the jsonb size limit |
| [#108](https://github.com/anym001/healthlog/pull/108) | The `daily_metrics` view and dashboards follow `TZ` |
| [#111](https://github.com/anym001/healthlog/pull/111) | Apple Health State of Mind entries in their own table |
| [#117](https://github.com/anym001/healthlog/pull/117) | Caffeine and HRV RMSSD in the metric registry |
| [#118](https://github.com/anym001/healthlog/pull/118) | Apple Watch heart rate notifications and ECG summaries |
| [#126](https://github.com/anym001/healthlog/pull/126) | "Outdoor/Indoor Cycling" workout names mapped to cycling |

Ongoing: the Companion itself was proposed upstream as the optional "dedicated web app"
([#107](https://github.com/anym001/healthlog/issues/107)), and there's more to come.

How the two fit together: the Companion reads HealthLog's tables **read-only**, through one checked
contract, and keeps its own data in its own schema. It never creates anything that depends on
HealthLog's schema, so HealthLog upgrades stay HealthLog's business.

- **HealthLog's own README** (set up the pipeline first): [`README.md`](../README.md)
- **Companion design and rules**: [`companion/docs/`](../companion/docs/) ·
  [`companion/CLAUDE.md`](../companion/CLAUDE.md)

## Bugs, ideas, questions

**[Open an issue on this fork](https://github.com/JHenzi/healthlog-ml/issues/new)**, for the Companion
*and* for this repository's HealthLog. We triage everything here first; what really belongs to
HealthLog gets reported upstream by us, reproduced on plain upstream and usually with a pull request.

<sub>Why this page lives in `.github/`: GitHub shows `.github/README.md` in place of the root one, so
the fork gets its own front page while HealthLog's `README.md` stays exactly as upstream wrote it.
Licence: AGPL-3.0, as HealthLog's ([`LICENSE`](../LICENSE)).</sub>
