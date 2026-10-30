# Reflection and prediction over time

*Research and options, 2026-10-30. Nothing here is decided or built.*
Roadmap B16, plan M7. The owner's brief, in short:

- The day rating is a **reflection**: "how do you *now* think the day went?"
  It changes. Monday felt good on Monday, looked bad from Tuesday, and
  Tuesday and maybe Wednesday were bad too, or we recovered.
- **One score isn't the answer.** Different things show different signs.
  They change, and we react to them.
- So this is a **prediction that has to learn over time**, looked at from
  several angles, with its limits stated plainly.

This page collects what the research says, the measures and models worth
considering, and the issues each one brings. The choices are listed at the
end as open questions.

## 1. What exists today

| Piece | State (2026-10-30) |
|---|---|
| Evening rating, "How was today?" (`rating.evening`) | 1–10, built-in since 2026-10-21; 8 days |
| Next-morning look-back, "Looking back, how was yesterday?" (`rating.lookback`) | 1–10; 8 days. **The question shows the evening answer** ("That evening you said 7"), which anchors it (§5) |
| The change between them (`rating.shift`) | next morning minus evening; 7 days |
| Good-day score (`goodday.score`) | four parts (active, sleep, water, mood), ranked against your own history, equal weights. **Mood is Apple's State of Mind only**: 21 days in total, sparse since 2026-10-20. The ratings are not in it |
| The engine | tests every series against every other (R17), with lags of up to 3 days and links spread over up to 7 days. The ratings are tested like any other series, but they have too few days to clear the bar yet |
| Learned weights (M7) | planned: the mix of good-day parts that best predicts the day rating on later days ([`analysis-engine.md`](analysis-engine.md), *Learned weights*) |

## 2. What the research says

### 2.1 How a day felt is not how it's remembered

- **Remembered and experienced differ.** The Day Reconstruction Method
  (Kahneman et al., 2004) was built because global reports of a day drift
  from what was felt in the moment. It reconstructs the day as episodes to
  narrow the gap. Later work with the method still finds memory and
  experience diverging, more so for unpleasant feelings.
- **Different lengths of time are recalled differently.** By the
  accessibility model (Robinson & Clore, 2002), a report about the last few
  hours draws on what was felt. A report about a day draws on memories of
  episodes, and one about a week or a month draws more and more on beliefs
  ("I'm a stressed person", "Mondays are bad").
- **Peaks and endings weigh more** in remembered episodes (Redelmeier &
  Kahneman, 1996: peak-end, duration neglect). Evidence for whole days is
  mixed: some studies find day-long evaluations don't follow peak-end.

**Implication:** the evening rating, the next-morning look-back and any
weekly look-back are **different measurements**, not better or worse
copies of one true value. The shift between them is information in itself.
It may track what happened after the day: a good day can turn sour once its
cost shows up the next morning.

### 2.2 Days carry over, and recovery takes time

- **Emotional inertia** (Kuppens et al., 2010) is the autocorrelation of
  affect from one occasion to the next: how much today's state persists
  into tomorrow. Higher inertia of negative affect goes with lower
  well-being. Results for positive affect are less consistent.
- **Caveat:** autocorrelation can be inflated when a slow-moving level (a
  rough week, a season) isn't modelled. Some of what looks like "one bad
  day leads to another" is a shared background. The engine already removes
  trend and weekday before testing (C3, C4); a state model has to as well.

**Implication:** "Monday bad, so Tuesday and maybe Wednesday bad, or we
recover" is a measurable pattern: carry-over and recovery time. It's also
easy to fool yourself with, because of shared background.

### 2.3 You, not the average person

Group findings often don't hold for the individuals in the group (Fisher,
Medaglia & Jeronimus, 2018: person-by-person correlations scatter widely
around the group's). The Companion is already personal (one person, one
history), so this argues against importing population weights as anything
more than a starting guess (roadmap B13 keeps that separate).

### 2.4 Ratings as noisy views of a hidden state

Time-series psychology treats daily self-reports as noisy measurements of a
latent state that moves from day to day:

- **State-space models** (a local level or AR(1) state with the Kalman
  filter) estimate today's state from all past observations. They handle
  missing days naturally, and in simulations of person-level EMA data they
  coped well with gaps. Several indicators can feed one state: the evening
  rating, the look-back, a weekly rating, mood, and possibly HRV or sleep.
  Each gets its own noise.
- **Regime switching** (hidden Markov models, alone or combined with a
  state-space model, after Kim & Nelson) adds discrete spells such as
  "good stretch" and "rough patch", with the chance of staying in or
  leaving each. That is the "or we recover" question in model form.
- **Dynamic structural equation modelling** (DSEM; Asparouhov, Hamaker &
  Muthén, 2018) is the general framework, including single-person (N = 1)
  series. It's heavier than we need, but its ideas carry over:
  person-specific dynamics, latent states, lagged effects between series.
- **Ordinal ratings:** a 1–10 rating isn't truly continuous. Ordinal
  state-space variants exist; with a 10-point scale, treating it as
  continuous is usually acceptable, and that's worth checking.

### 2.5 Forecasting that keeps learning

- **Personal mood forecasts from sensor data** are an active field.
  Per-person models using phone and wearable data have predicted next-day
  affect, or weeks-ahead depression scores, better than using past scores
  alone. The studies are small or not yet replicated across settings, and
  the authors say so.
- **Relationships drift.** Concept drift is the textbook name (Gama et al.,
  2014): what predicted a good day in October may not in March (new job,
  season, training block). The remedies are a moving or down-weighted
  window, change detection, and models refitted on a schedule. Each trades
  staying current against being noisy.
- **Score the forecasts honestly.** Every forecast is stored before the
  outcome arrives, and later compared with what you said. Showing that
  track record ("forecasts like this were within 1 point on 7 of 10 days")
  is the evidence for the model (R13). Time-ordered validation only (R9).

### 2.6 Measuring changes the thing measured

- **Measurement reactivity:** being asked about your mood every day can
  change mood or how it's reported. The evidence is thin and mixed, but the
  effect is plausible over months.
- **Feedback:** a shown forecast ("tomorrow looks rough") can change what
  you do. That may be good for you, but it breaks the forecast's track
  record and can come true just by being shown. Any forecast that's shown
  becomes part of the data, and the model has to know what was shown.

## 3. Measures worth considering

A list to choose from, not a plan. Each costs a little attention every day
or week, and the design rule is few choices with good defaults
([`design.md`](design.md)).

| Measure | What it captures | Cost / issue |
|---|---|---|
| Evening rating (have) | the day as it ends | none new |
| Next-morning look-back (have) | the day after a night's sleep; the shift | **anchored** on the evening answer while it's shown (§5) |
| **Blind** look-back | the same without the anchor | small UI change; the shift becomes cleaner but noisier |
| **Later look-backs** (day +2, +3) | how a day keeps getting re-judged | more prompts; likely low response. Better covered by the weekly look-back |
| **Weekly look-back** (e.g. Sunday evening) | "How was this week?" on 1–10, plus **pick the best and the worst day** | one prompt a week. Picking days avoids scale drift (a ranking, not a number). Draws on belief more than memory (§2.1) |
| Monthly look-back | slow-moving well-being | belief-heavy; mostly for the long view |
| A few extra dimensions (energy, stress, satisfaction) | "different things show different signs" | each one adds a daily tap. Some already exist passively (HRV, sleep, stress proxy) or as trackers you can create |
| Re-rate any past day | revisions as they happen | a "change my mind" button; every revision kept with its time (event log) |

## 4. Models worth considering (from simple to rich)

Each needs its validation suite before it ships (R8). None says *causes*
(R10).

1. **Descriptive, in the existing engine.** Distribution of the shift;
   carry-over (lag-1 and lag-2 autocorrelation of the rating, after
   weekday and trend); **recovery after a low day** (days until the rating
   returns to your usual range); which series go before a downward shift.
   Mostly new ways of reading the engine's existing lagged tests. Earliest
   possible, with weeks of data.
2. **A latent day-state model.** A Kalman-filter state fed by the evening
   rating, the look-back, the weekly look-back and mood, each with its own
   noise. Output: an estimate of "how things are going" with an
   uncertainty band, which fills gaps without inventing values. With a
   simple autoregressive state, the carry-over estimate comes out of the
   same fit.
3. **Spells (regime switching).** "Good stretch" and "rough patch" states
   with stay/leave probabilities. Output: "rough patches have tended to
   last about 2 days". Needs several patches to learn from, so months, not
   weeks.
4. **Forecasts with a track record.** Tomorrow's rating (or the latent
   state) from today's data, refitted on a schedule over a moving window,
   with every forecast stored and scored against the naive "same as today"
   and "your average" baselines. Shown only while it beats them (R9). This
   is the model that "learns over time".
5. **Learned good-day weights (M7, planned).** Unchanged in spirit, but the
   anchor becomes the latent state or a combination of ratings rather than
   one evening number.

**Several signals, not one score.** The page could show a few signals side
by side, each with its own direction and evidence: the equal-weight
good-day score (the fixed reference), the latent state, the forecast,
carry-over and recovery. That fits "different things show different signs"
and keeps the one-number trap out.

## 5. Issues and limitations

- **Very little data so far.** 8 ratings. Carry-over needs roughly 30+ days
  to estimate loosely; spells and drift need months. The engine's minimum
  days and FDR bar keep early numbers quiet, which is correct.
- **Anchoring.** The look-back shows the evening answer, so the shift is
  biased toward 0. Showing it is friendlier, hiding it is cleaner. This is
  a decision for the owner (§7), and once made, the change should be logged
  so data from before and after isn't mixed blindly.
- **Missing isn't random.** Ratings may be skipped on the worst (or the
  busiest) days (risks.md C9). State-space models assume gaps are
  uninformative unless told otherwise. Reminders help; coverage is shown.
- **Scale drift.** What a "7" means changes over months. Rankings (best and
  worst day of the week) and the per-person percentile ranks the good-day
  score already uses are more robust than raw numbers.
- **Memory and belief bias.** Longer look-backs lean on beliefs (§2.1). A
  weekly rating isn't a better truth than the dailies, just a different
  one; the two disagreeing is a finding.
- **Circularity.** If the evening rating goes into the good-day Mood part
  (proposed 2026-10-29), the learned weights (M7) can't use it as their
  anchor without predicting themselves. Either the anchor changes (latent
  state, look-back, weekly) or the rating stays out of the score.
- **Shared background vs carry-over.** A rough week can look like "bad days
  cause bad days". Trend, weekday and spans (vacation, sickness: M4 part 2)
  must be removed first (C3, C4).
- **Overfitting and drift.** Few days and many candidate series. Regularised
  models with shrinkage toward the simple baseline, time-ordered validation,
  and refits on a schedule rather than continuously (C5, C6).
- **Reactivity and feedback.** Showing forecasts changes behaviour (§2.6).
  Store what was shown, and consider showing forecasts only after the
  evening rating is in, so the forecast can't steer the rating.
- **Wording.** All of it is association and forecast language (R10). Not
  medical; health-relevant patterns may suggest talking to a clinician.
- **Day boundary.** The day ends at 04:00, so a late-night look-back still
  counts for the same day; the DST days (23 h, 25 h) need the usual care
  (R14).

## 6. Possible order (not decided)

1. **Now, collecting only:** decide whether the look-back is blind; maybe
   add a weekly look-back. Data starts accruing; nothing is analysed yet.
2. **About 30 days in:** the descriptive layer (§4.1): shift, carry-over,
   recovery, inside the existing engine and its FDR family.
3. **About 60 days in:** the latent state (§4.2) with its validation suite
   (planted carry-over and noise must be recovered; pure noise must give no
   carry-over).
4. **About 90 days in:** forecasts with a track record (§4.4) and the
   learned weights (§4.5) anchored on the state.
5. **Months in:** spells (§4.3) and drift handling.

## 7. Open questions for the owner

1. Should the next-morning look-back hide the evening answer?
2. Should there be a weekly look-back (a rating, and pick the best and
   worst day)? On which day?
3. Should the evening rating go into the good-day Mood part, given the
   circularity with M7 (§5)?
4. Should there be a few extra daily dimensions, or should the passive
   signals and your own trackers cover that?
5. Should forecasts ever be shown before you've rated the day?

## References

- Kahneman, D., Krueger, A. B., Schkade, D. A., Schwarz, N., & Stone, A. A.
  (2004). A survey method for characterizing daily life experience: the Day
  Reconstruction Method. *Science*, 306(5702), 1776–1780.
- Robinson, M. D., & Clore, G. L. (2002). Belief and feeling: evidence for
  an accessibility model of emotional self-report. *Psychological
  Bulletin*, 128(6), 934–960.
- Redelmeier, D. A., & Kahneman, D. (1996). Patients' memories of painful
  medical treatments. *Pain*, 66(1), 3–8.
- Kuppens, P., Allen, N. B., & Sheeber, L. B. (2010). Emotional inertia and
  psychological maladjustment. *Psychological Science*, 21(7), 984–991.
- Fisher, A. J., Medaglia, J. D., & Jeronimus, B. F. (2018). Lack of
  group-to-individual generalizability is a threat to human subjects
  research. *PNAS*, 115(27), E6106–E6115.
- Asparouhov, T., Hamaker, E. L., & Muthén, B. (2018). Dynamic structural
  equation models. *Structural Equation Modeling*, 25(3), 359–388.
- Kim, C.-J., & Nelson, C. R. (1999). *State-Space Models with Regime
  Switching*. MIT Press.
- Gama, J., Žliobaitė, I., Bifet, A., Pechenizkiy, M., & Bouchachia, A.
  (2014). A survey on concept drift adaptation. *ACM Computing Surveys*,
  46(4), 44.
- Personal mood forecasting from phone and wearable data: e.g. a
  per-person spline-plus-model approach (medRxiv 10.1101/2022.10.12.22281007,
  later in *npj Digital Medicine*), and next-day affect from wearables in
  20 students (arXiv 2201.11230). Small samples; treat as proof of concept.
- State-space handling of gaps in person-level EMA data: arXiv 2206.14343.
