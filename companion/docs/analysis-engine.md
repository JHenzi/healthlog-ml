# Analysis engine

What the insight engine does today (M5 v1), how it guards against false
findings, and how it was validated. Design background:
[`companion-app-design.md`](companion-app-design.md) §4. Code:
`app/analysis/` (`pure.py` statistics, `engine.py` tests and the FDR pass,
`sentences.py` wording, `run.py` storage). Tunables:
`app/analysis/constants.py`.

## What it looks for

The engine reads the daily feature table (see [`architecture.md`](architecture.md))
and runs at the end of every refresh: nightly at 04:15, on *Rebuild now*, or
via `companion refresh`.

| Horizon | Question | Method |
|---|---|---|
| **Day** | Do two series move together on the same day, or does one go with the other's value **the next day**, in either direction? | Spearman on residuals; a yes/no series (e.g. "felt anxious") against a measure: Mann-Whitney + Cliff's delta, with medians in real units; two yes/no series: Fisher's exact test |
| **Week** | Is the last 7 days different from the 28 before? | difference in means with autocorrelation-adjusted sizes |
| **Month** | Is the last 28 days different from the 56 before? | same |
| **Weekly rhythm** | Does a series differ by weekday? | Kruskal-Wallis on the de-trended series |

Only series of **different families** are related. Families group series
that are linked by definition: steps, distance and energy (activity), sleep
and its stages, heart rate with HRV, stress and energy reserve (vital, since
stress and energy reserve are computed from heart rate), and the mood series.
"Steps go with distance" is true but tells you nothing.

## Guardrails

- **Residuals.** Before two series are related, each loses its weekday
  profile and a 28-day centred trend. "Both are higher on weekends" and "both
  drifted up this month" are not relationships. The suite plants exactly
  those confounders and checks they stay quiet.
- **Effective sample size.** Consecutive days are not independent. Spearman
  and Mann-Whitney p-values use Bartlett's effective n over the first ten
  autocorrelation lags. Window comparisons shrink each window's n by the
  AR(1) variance inflation of a mean.
- **One multiple-testing family.** Every p-value of a run (all pairs × lags,
  all changes, all weekday tests) goes through one Benjamini-Hochberg pass
  at a 10% false-discovery target (R8).
- **Effect floors.** |ρ| ≥ 0.25, |Cliff's δ| ≥ 0.25, changes ≥ 15% *and*
  |δ| ≥ 0.33, weekday η² ≥ 0.06. A tiny effect on lots of data stays quiet.
- **Minimum support.** A series needs 21 days, a yes/no series 8 days on
  each side, and a change window 70% of its days observed.
- **One line per pair.** Of a pair's same-day and next-day results, only
  the strongest is shown. The others are tested (and count in the FDR
  family) but not repeated.
- **Wording.** Sentences say *tends to*, *goes with*, *is followed by*, never
  causal or diagnostic words. Each one carries its number of days and a
  strength word. A lint in the tests enforces both (R10, R13). The explain
  view shows the method, effect, raw and adjusted p, and effective n.

## Likely ranges

Every association and change carries a 95% **likely range**, drawn on
Discoveries and the evidence page as a bar with a tick where "no effect"
would be (design 1b/1c). A range that crosses the tick is drawn quieter.
Each uses the same effective sample size as its test, so carry-over between
days widens it:

| Finding | Range |
|---|---|
| Spearman ρ | Fisher z with Fieller's variance 1.06 / (n − 3), on the effective n |
| Cliff's δ (yes/no vs a measure) | through the AUC, Hanley-McNeil variance widened by n / effective n |
| φ (two yes/no series) | Fisher z on n |
| week / month change | the mean shift's t interval on the effective window sizes, as % of the earlier window |

Weekday rhythms have no range. Stored in `insights.details` (`ci`, `pct_ci`).

## Adjusted re-check

Each reported relationship is re-read allowing for everyday drivers,
`ADJUST_FOR` (today: total sleep and steps), skipping a driver from either
side's family. It is a partial Spearman correlation on the same residuals
(a yes/no side as 0/1), with each driver on the later day and, for a
next-day finding, on the earlier day too, plus a likely range on the
effective n less the covariates. The verdict:

- **holds**: same sign, and the adjusted range excludes 0;
- **weaker**: same sign, at least half the unadjusted strength, but the range
  reaches 0;
- **largely accounted for**: otherwise.

It adds no p-values to the FDR family: it reads findings that already
cleared the bar, so it can't create a discovery, only qualify one. Stored as
`insights.details.adjusted`; shown on Discoveries and the evidence page.

## Validation (tests/stats)

Seeded synthetic data, 100 days. The suite runs 20 seeds per check on every
push and 200 nightly (`STATS_SEEDS`).

| Check | Requirement |
|---|---|
| planted same-day link (ρ ≈ 0.6) | found in ≥ 90% of datasets |
| planted next-day link, with its direction | found in ≥ 90% |
| planted yes/no effect (+1 SD on 30% of days) | found in ≥ 80% |
| shared weekday pattern only | reported in ≤ 10% |
| shared trend only | reported in ≤ 10% |
| 12 independent AR(1) series (φ = 0.5): any relationship is false | ≤ 15% of datasets |
| two planted links among 10 AR(1) series: share of false reports | ≤ 15% on average |
| weekly level shift found / flat data quiet | ≥ 90% / ≤ 10% |
| weekday rhythm found | yes |
| ρ range covers the planted value (independent / AR(1) φ = 0.6 days) | 90–99% / 88–99% of 400 datasets (measured: 95% / 96%; a range on the plain n covers only 79% on the AR(1) days) |
| δ range and change range cover the planted value | ≥ 88% of 400 datasets |
| a link planted only through sleep reads "largely accounted for" (two measures) | ≥ 85% of the datasets that report it |
| a direct link with independent sleep "still holds" | ≥ 85% |
| a yes/no link planted through sleep reads "holds" | ≤ 15% |

**What the suite caught (2026-10-17).** The first version flagged
relationships in **35%** of pure-noise datasets. Measuring each test on null
data showed why:

| Test | False positives at p < .05 |
|---|---|
| Spearman, 1-lag effective n | 7–11% |
| week/month change as a plain Mann-Whitney test | 24–33% |

Seven days in a row of autocorrelated noise easily look like a "change", and
because every p-value shares one FDR pass, that flood of small p-values also
let relationship tests through. With ten-lag effective n (5.4%) and the
autocorrelation-aware mean-shift test (5.9%), every check passes at 20 and at
100 seeds.

## On real data (2026-10-17)

The first live run tested 701 patterns across 26 of 76 series (the others
have fewer than 21 days) and reported none. The strongest candidate was
ρ = −0.65 on 25 days (raw p = 0.0007), which adjusts to 0.26 after 701 tests.
That is the intended behaviour: a few weeks of data can't separate such a
link from chance. Expect findings once sleep history is back (risks.md L3) and
mood and workouts arrive automatically. The Insights page shows these run
numbers so an empty list explains itself.

## Not yet

- **Distributed lag models** (effects spread over days 1–7) need months of
  daily data, so they are not in v1.
- **Within-day** event-locked responses: M6.
- **ML models**: M7.
