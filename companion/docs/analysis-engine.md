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
"Steps go with distance" is true but tells you nothing. A composite is
linked by definition to the families it is built from: the good-day score
(below) is never related to activity, sleep, water or mood series.

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

For each ordered pair of analysed series from different families (every
series is tried on both sides, R17), one regression of the second on the
first today and on each of the 7 days before, with the eight lag weights
constrained to a smooth curve (an Almon polynomial of degree 2). That makes
a whole week of lags one curve with 3 degrees of freedom, not eight. Both
directions are fitted and the pair keeps the one with the smaller p,
doubled (Bonferroni), so a pair is **one** test in the FDR family. Without
that, trying both orders (R17) pushed two series with a shared weekday
pattern to 10.5% false links (target 10%); with it, 7% (200 seeds,
2026-10-20).

**Calibration for every pair (2026-10-20).** Running the curve test on
every pair (R17) exposed an optimistic effective n: it came from one lag
column, but the fitted curve weighs a week of lags and drifts more slowly
than any one of them. With 10 noise series and two planted links, 16% of
reported links were false (target 15%); every false curve was a broad,
flat one (chance slow co-drift). The effective n now comes from the fitted
curve's predictor and y without the curve: 10.2%, with the planted spread
effects still found. The curve's share is also adjusted for its fitted
weights on the effective n. Slow harmonics in the nuisance model made it
worse (28%) and were dropped. It needs 56 overlapping days. A curve is reported only
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

Each reported relationship is re-read allowing for the series the run
itself reported as linked to **both** sides (day-level links), at most
`ADJUST_MAX_DRIVERS`, the most strongly linked first, skipping either side's
family. No list of "usual suspects" (R17): when nothing is linked to both
sides, there's no re-check. It is a partial Spearman correlation on the same residuals
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

## Weather and the almanac

Tested like every other series (R17: measure, don't presume): both time
orders, week/month changes and weekday rhythm included. A link like
"headaches tend to be followed by a pressure rise the next day" is reported
as measured, in time order and in association language (R10). All 15 daily
weather features are analysed; near-duplicates (high, low and mean
temperature) share the `weather` family, so they are never tested against
each other. Feature definitions: `app/outside.py`.

The almanac (`app/almanac.py`) is computed here from the date: day length,
the moon (share lit), public holidays (yes/no) and days until the next one.
Day length moves smoothly with the season, so the trend removal leaves
little of it for the day-level tests; its week/month changes are real and
reported. Holidays mostly fall on Mondays, so a holiday finding can overlap
the weekday rhythm; the explain view shows both.

## The day rating

The Companion's own measure of the day, built in (`app/dayrating.py`): a 1–10
"How was today?" each evening and "Looking back, how was yesterday?" the next
morning, stored on the day it is about. It can't be removed or archived, so
it's always there to be answered, and an unanswered day is missing, never a
default (R7). Three daily series come from it, one family (linked by
definition, never tested against each other):

| Feature | What |
|---|---|
| `rating.evening` | the evening rating |
| `rating.lookback` | the next-morning rating |
| `rating.shift` | next morning minus evening, on days with both |

It's a measurement, not a theory (R17): the engine tests all three against
everything, the good-day score included, so "does the computed score agree
with how the day felt?" is answered by the data. It is the anchor for the
learned good-day weights below.

## The good-day score

An outcome the user defined, not a theory the engine holds (R17): a good day
is active, not short on sleep or water, and has a good mood. `app/goodday.py`
builds it from four parts with equal weight:

| Part | Components |
|---|---|
| Active | steps, exercise minutes, active energy (their mean) |
| Sleep | total sleep, the night before the day |
| Water | water logged |
| Mood | mean State of Mind valence |

Each component is ranked against your own history (percentile among all
recorded days, ties sharing a rank; a component needs 14 days). The score is
the mean of the parts present that day, with at least two of them. A part
without data is left out, never counted as 0 (R7). Higher counts as better for
every part, because that is the definition; goals (a sleep or water target)
are a later setting. Ranks use the whole history, so a day's score can shift a
little as days arrive. Only complete days are scored (today's partial steps
would read as a poor day).

**Equal weights are the standard, not the end state.** The parts don't
matter equally for everyone: for one person sleep may go before a good mood
and an active day, for another it may not. The plan is a **personal, learned
score shown side by side with the standard one** (below, *Learned weights*).
The standard stays: it is the fixed reference the learned one has to beat,
and it doesn't move when the model is refitted.

`goodday.score` is a daily feature analysed like every other series, in the
same FDR family: relationships in both time orders, spread over days,
week/month changes and weekday rhythm. It is not tested against the families
it is built from (activity, sleep, nutrition, mood): those links hold by
construction. The **Good days** page lists the best days (top quarter of
scored days, from 12 scored days on) and, for each reported link with the
score, the other series' median on best days and on the rest. That
comparison is descriptive: it adds no tests, the finding above it is the
evidence.

### Learned weights (planned, with M7)

The weights have to be learned from something other than the score itself,
or they only learn the score's own formula back. What anchors them, in order
of preference:

1. **Your own rating of the day.** The built-in day rating (above): the
   evening rating and the next-morning look back. The weights are the mix of parts that best
   predicts your rating on later days. This is the most direct: "good" as you
   felt it, not as we computed it.
2. **What carries over.** A part counts more when it goes before the other
   parts on the next days, such as sleep going before mood and activity. The
   engine already measures these lagged links (day-level lags and the
   spread-over-days curves). The wording stays associative (R10): "goes
   before", never "drives".
3. **Shared variation** (the first principal component): parts that move
   together count more. This needs no anchor, but it rewards parts that
   overlap, so it is a fallback only.

How it has to behave:

- **The data picks the weights (R17).** The parts come from your definition;
  only their mix is learned. Weights are non-negative and add up to 1. The
  parts' components (steps against exercise minutes inside *active*) can be
  learned the same way.
- **Shrunk toward equal.** With little data the learned score equals the
  standard one and moves away only as the evidence grows. Twenty days don't
  get to say that mood doesn't matter.
- **Time-ordered validation (R9).** The model is fitted on earlier days and
  scored on later ones. It is shown only if it beats the standard score at
  predicting the anchor on held-out days; otherwise the page says "not yet
  different from the standard". It never sees days after the one it scores.
- **Shown side by side.** The page shows both scores, the learned weights
  next to the equal ones, the days behind them (R13), and how much better
  the learned score predicts the anchor.
- **Needs** about 60–90 days with the anchor. Ratings started in late
  October are enough around January.
- **The anchor** (decided 2026-10-30): the day ratings (evening, a blind
  next-morning look-back, a Sunday weekly look-back) are the owner's
  overall judgement, not mood, and become **inputs** to the good-day score.
  Weights are then learned against a *later, different* judgement (the
  look-back for the evening, the weekly rating for the week), never the
  same rating. Methods: [`reflection-and-prediction.md`](reflection-and-prediction.md) §4c.

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
| headaches the day before a pressure rise, found with headaches first | ≥ 80% (measured: 92.5% of 200) |
| unrelated weather with a season: datasets reporting any relationship | ≤ 15% (measured: 13% of 200; 8.5% before R17 added the second time order) |
| a composite against a series it is built from / a series linked through the data | never tested / found |
| planted moon → sleep link (±0.3 h), found | ≥ 80% (measured: 86% of 200) |
| the moon and holidays against unrelated series: datasets reporting a calendar link | ≤ 15% (measured: 1.5% of 200) |

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
