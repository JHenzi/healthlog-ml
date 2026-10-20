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
| **Over days** | Does something you do or get (a tracker, sleep, caffeine, daylight) go with another series over the following week, peaking 2+ days later? | distributed lag model over days 0–7, one test per pair (below) |

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

## Links spread over days

For each exposure (trackers, total sleep, caffeine, time in daylight) and
each series of another family, one regression of the outcome on the
exposure today and on each of the 7 days before, with the eight lag weights
constrained to a smooth curve (an Almon polynomial of degree 2). That makes
a whole week of lags **one** test with 3 degrees of freedom in the FDR
family, not eight. It needs 56 overlapping days. A curve is reported only
when its largest weight is 2 or more days later; same-day and next-day links
are the day-level tests' job. The evidence page draws the curve as one bar
per day.

**Calibration, and what the suite caught (2026-10-19).** The first version
reused the other tests' residuals (weekday profile and a 28-day rolling
trend removed) and corrected the F test by the effective n. On noise it
said p < .05 in 8.5% of independent and 11% of autocorrelated datasets: the
rolling detrend leaves structure shared by both series, and a regression on
eight lags finds it. Fitting the weekday profile and a straight-line trend
*inside* the regression, with AR(1) errors (Cochrane-Orcutt) and the F test
shrunk to the effective n of the filtered exposure and residuals, measures
4.5% (independent), 4.8% (AR(1) φ = 0.6), 5.8% (shared trend), 6.2% (shared
weekday pattern) and 8% on very slowly drifting series (φ = 0.9), while
finding 98.5% of planted spread effects at p < .01. Variants with more
estimated error parameters (AR(2), AR(3)) or plain differencing were looser
or weaker; the numbers are in the PR.

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

## Outside data (weather)

Weather can go with what follows it, but nothing you do changes it. So a
feature of an outside family (`EXOGENOUS_FAMILIES`, today `weather`) is only
ever the earlier or same-day side of a relationship: same day, and weather
today against the outcome tomorrow, never the reverse. It never gets its own
week/month change or weekday test (a colder month is the season, not news),
and weather is never paired with weather. Three weather features are
distributed-lag exposures (`DLM_EXPOSURES`: temperature, pressure change,
PM2.5). Of the 15 daily weather features, 7 are analysed; the rest are shown
but not tested, so near-duplicates (high, low and mean temperature) don't
dilute the FDR family. Feature definitions: `app/outside.py`.

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
| a link spread over days 2–4 is found, with its peak at 2–4 days | ≥ 80% |
| the curve test on noise (independent; AR(1) φ = 0.6) | p < .05 in ≤ 7% of 400 datasets |
| the curve test with a shared trend or weekday pattern | ≤ 8% |
| noise through the whole engine reports a spread link | ≤ 15% of datasets |
| a same-day link is reported as spread | ≤ 10% |
| a link planted only through sleep reads "largely accounted for" (two measures) | ≥ 85% of the datasets that report it |
| a direct link with independent sleep "still holds" | ≥ 85% |
| a yes/no link planted through sleep reads "holds" | ≤ 15% |
| planted weather → next-night sleep link, found with weather first | ≥ 80% (measured: 100% of 200) |
| a series that the weather merely follows is never reported as its cause; weather never gets a change or weekday finding, even with a season and a weekend pattern | never |
| unrelated weather with a season: datasets reporting any relationship | ≤ 15% (measured: 8.5% of 200) |

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

- Streaks and records are descriptive, not tests: `app/highlights.py`
  (no p-values, outside the FDR family).
- **Day length and public holidays** as outside features (computed locally).
- **Within-day** event-locked responses: M6.
- **ML models**: M7.
