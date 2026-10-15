# HealthLog Companion: feature design

*(Working name.)* A **personal health and lifestyle learning app**. You define
whatever you want to track (cups of coffee, a productivity score, the time
you ate lunch, when you first opened social media, whether you saw friends) and
keep a short diary. The Companion combines that with everything HealthLog
already measures, and learns which parts of your life move together:

- *Does coffee make you more active, and for how long?*
- *Does a bad night's sleep make family friction more likely the next day,
  or is it the other way round?*
- *Do days you write about shopping (Target, Walmart, Amazon, Kroger) come
  with more anxiety?*
- *Is your productivity better when lunch is before 12:30?*

HealthLog stays what it is, the sensor pipeline (Apple Health in, nightly
statistics out). The Companion adds **the inputs a watch can't see** and turns
the combined data into **plain-language insights**, not dashboards.

Related notes: [`tagging-and-daily-review.md`](tagging-and-daily-review.md)
(capture paths, Siri constraints, missing-data reasoning) and
[`webapp-ingest-analysis.md`](webapp-ingest-analysis.md) (why the upstream
ingest token must not be reused).

---

## 1. Design principles

1. **Trackers are data, not code.** A new measure is something the user
   creates in the app, not a migration or a deploy. That's the same principle
   HealthLog applies to its metric registry, extended to user-defined input.
2. **Typed observations.** Every tracker has a *type* (count, scale, time of
   day, …), and the type decides the input widget, validation, daily features
   and statistics. Flexible input still yields correct analysis.
   **Capture is structured: nothing is guessed.** Values come from menus and
   typed prompts, never from a language model interpreting free text.
3. **Raw in, features out.** Store what the user actually entered, verbatim
   and timestamped. Derive the analysable daily features (count, first time,
   average, …) from it, so features can be added or fixed later and
   recomputed over all history.
4. **Every source is one feature space.** HealthLog metrics, user trackers and
   diary themes all become rows of one daily table, so anything can be
   related to anything.
5. **Honest statistics.** Minimum support, multiple-testing control, effect
   sizes in real units, *n* shown on every insight, and correlation ≠
   causation stated plainly.
6. **Never wreck upstream** (§8): no edits to HealthLog's code or tables, and
   nothing in the database that depends on them.
7. **Local first.** Health data, tracker data, diary text and embeddings never
   leave your hardware. Outside data sources (§2.5) are opt-in and
   **fetch-only**: they pull public data in and never send personal data out.

---

## 2. Trackers: the flexible measurement model

### 2.1 Tracker types

| Type | Example | Input widget | Raw value | Daily features derived |
|---|---|---|---|---|
| **count** | cups of coffee, glasses of water | stepper / "+1" tap | integer per entry (usually 1) | total; first & last time *(if timestamped)*; time after waking |
| **scale** | productivity 1–5, cortisol-like intensity 0–10, pain 0–10 | slider with anchor labels ("1 = nothing done … 5 = best day") | number in [min, max] | mean, max (and min) per day |
| **check** (yes/no) | meditated, alcohol, saw friends | toggle | 0/1 | any (0/1) |
| **quantity** (with unit) | caffeine mg, money spent $, km cycled | number + unit | number | sum or mean (per tracker) |
| **duration** | meditation minutes, commute time, screen time | minutes / h:mm | minutes | sum |
| **time of day** | lunch time, first social-media use (or another habit you're watching), bedtime | time picker ("now" default) | local timestamp | first / last time of the day, as minutes after midnight **and** minutes after waking |
| **choice** | lunch: home / takeout / skipped; workplace: office / home | chips, single or multi | option key(s) | one 0/1 feature per option |
| **moment** (event) | anger, anxiety, headache onset, argument | one tap + optional intensity and cause | timestamp (+ intensity, cause) | count, max intensity, first time; **plus intraday analysis** (§4.3) |
| **span** (context) | vacation, sick, travel, period, house guests | start / end | date interval | 0/1 mask per day; used to condition or exclude (§4.4) |
| **note / diary** | free text | text box or dictation | text | themes, concepts, sentiment (§3) |

**Time-of-day needs special care.** Clock times wrap at midnight (a 00:30
bedtime is *later* than 23:30, not earlier), and "first use at 19:40" means
something different on a day you woke at 06:00 than at 11:00. So time
trackers produce **two** features: minutes after local midnight, rolled so
the day boundary sits at a configurable hour (e.g. 04:00), and minutes after
waking (wake time from HealthLog's `sleep_sessions`).

### 2.2 Tracker definition (all data)

```yaml
# what the user fills in when creating a tracker (stored as a row)
key: coffee                # stable id; display name can change freely
name: Coffee
type: count
unit: cups
aggregation: sum           # default per type; overridable
timestamped: true          # record when each cup happened → first/last-time features
polarity: neutral          # good / bad / neutral: only affects insight wording
category: food & drink
aliases: [coffee, espresso, latte, cup of joe]   # for voice/text parsing
prompt: { in_review: true, reminder: null }
```

```yaml
key: productivity
type: scale
scale: { min: 1, max: 5, labels: { 1: "nothing done", 3: "normal", 5: "best day" } }
aggregation: mean
polarity: good
prompt: { in_review: true }
```

### 2.3 Changing a tracker without corrupting history

- **Display name, category, aliases, prompts, polarity** can be changed freely.
- **Type, unit and scale range** are locked once data exists. Changing 1–5 to
  1–10 would silently make old values mean something else. Instead the app
  offers *"create a new version"*: the old tracker is archived, the new one
  linked as its successor, with an optional explicit mapping (e.g. ×2) if the
  user wants the history merged for analysis.
- **Archiving** hides a tracker from input, but its history stays in the analysis.

### 2.4 Starter packs

Picking from ready-made packs gets a new user past the blank page: *Sleep
hygiene* (caffeine, alcohol, screens in bed, bedtime), *Mood & energy*
(scales + moments), *Productivity* (scale, deep-work duration, start time),
*Substances*, *Food* (meal times, takeout, snacks), *Social & family*,
*Symptoms* (a configurable checklist, e.g. headache, fatigue, brain fog),
*Women's health*. Packs are just preset tracker definitions; everything stays
editable.

### 2.5 Outside data sources

Some things that affect health and mood aren't measured by the watch *or*
logged by the user. They're facts about the world. Each source becomes a set
of daily features (and hourly ones where useful for within-day analysis),
like any other attribute.

| Source | Features | Why it matters |
|---|---|---|
| **Weather** | temperature (min/max/feels-like), humidity, **barometric pressure and its 24 h change**, precipitation, cloud cover, wind, UV index | pressure swings are a commonly reported headache trigger; heat and humidity affect sleep and HR; grey days affect mood |
| **Air quality** | AQI, PM2.5, ozone, pollen (where available) | breathing, sleep, headaches, allergies |
| **Daylight** | sunrise, sunset, day length (**computed locally**, no network) | seasonal mood, sleep timing, the cortisol rhythm |
| **Calendar** *(later)* | meeting count, busy hours, early first meeting (from a local CalDAV/ICS feed) | workload as a covariate for stress and productivity |
| **Public holidays / workdays** | holiday flag (local library, no network) | separates workday from holiday effects |
| **Other tracking apps** | their exported history (CSV import) | run alongside them; nothing lost |

**Privacy rules for outside sources:**
- **Opt-in**, per source, off by default.
- **Fetch-only**: requests contain only what the source needs (a coarse
  location and a date range), never health or personal data.
- **Coarse, fixed location**: the user's home area rounded to roughly 10 km,
  set in config. No GPS tracking and no per-day location. (Travel is handled
  by the `travel` span; an optional per-span location can come later.)
- **Prefer key-less, no-account providers.** Open-Meteo, for example, offers
  forecast and historical weather (so past data can be backfilled for the
  whole history) and air quality, without an API key. A local weather
  station or Home Assistant sensor is the fully offline alternative.
- **Fetched data is cached** in our schema, so each day is fetched once and
  analysis never needs the network.

---

## 3. Diary: short entries, learned from with embeddings

Structured trackers only capture what you thought to track. A **quick diary
entry** ("Target run after work, parking lot was chaos, snapped at the kids")
captures what you *didn't*, and the system can find structure in it later.

### 3.1 Pipeline (all local)

```
entry text ──► embedding (vector)           ──► themes (clusters)  ──┐
          └─► structured extraction (local LLM): places/brands,      ├─► daily features
              people, activities, sentiment ──► concepts            ──┘   → insight engine
```

1. **Embeddings.** Each entry is embedded with a small local model.
   - *Default*: a compact sentence-embedding model inside the companion
     container (CPU is plenty for short texts). Diary text then never leaves
     the server.
   - *Option*: the existing Ollama host (`nomic-embed-text` or similar),
     which sends text over the LAN to that machine.
   - Store `model` and `dim` with every vector, so switching models means a
     clean re-embed, never mixed vectors.
2. **Storage.** The pinned TimescaleDB image ships **pgvector 0.7.2**
   (available, not yet enabled), so vectors live in Postgres, created inside
   the `companion` schema by the bootstrap script. At personal scale (a few
   thousand entries) even brute-force similarity in NumPy is instant, so
   pgvector is a convenience, not a dependency. If a future upstream image
   dropped it, a `float4[]` column plus NumPy is the fallback.
3. **Concepts** (user-defined, zero-shot): you define *"shopping"* with a few
   seed phrases ("went to Target", "Walmart run", "Amazon order", "grocery
   shopping at Kroger"). Each entry gets a similarity score to the concept,
   and the day gets `concept_shopping = 1` if any entry clears the
   threshold. The threshold is tuned by showing you the nearest and
   borderline entries to confirm or reject: a few clicks of labelling, not
   ML work.
4. **Themes** (discovered, unsupervised): nightly clustering of all entry
   vectors (e.g. HDBSCAN). The local LLM names each cluster from its most
   representative entries ("work deadlines", "kids' bedtime", "driving").
   Themes with enough days become features automatically. You can **promote**
   a theme to a named concept, rename it, or hide it.
5. **Structured extraction** (local LLM, constrained JSON output): brands and
   places (`target`, `kroger`), people or roles (`mom`, `boss`), activities
   (`driving`, `cooking`), and entry sentiment/emotion. It's explainable and
   complements embeddings: "Target" and "Walmart" are near each other as
   vectors, but the extraction says *which* one.
6. **The diary is analysis input only.** It never creates or changes tracker
   data. Embeddings, themes and extraction turn text into *features* for the
   insight engine, always shown with the entries behind them (§3.2).
   Tracker data comes only from structured capture (§5).

### 3.2 Explainability is non-negotiable

An insight from text must show its **evidence**: *"Days with shopping-related
entries had higher anxiety (median 3 vs 2, 14 vs 61 days)"*, followed by the
actual entries that matched. Text features are numerous and fuzzy; being
able to inspect them is what makes them trustworthy, and it's also how you
catch a concept that matches the wrong things.

---

## 4. The insight engine

Runs nightly (e.g. 04:15, after HealthLog's 03:30 analysis), inside the
companion container.

### 4.1 One daily feature table

One row per local day. Columns come from:

| Source | Examples |
|---|---|
| HealthLog (read-only, §8.3) | sleep duration/efficiency/bedtime, HRV, resting HR, steps, active energy, stress score, energy reserve, training load |
| Trackers (§2) | `coffee_total`, `coffee_first_after_wake_min`, `productivity_mean`, `lunch_time_min`, `social_media_first_after_wake_min`, `alcohol_any`, `lunch_choice_takeout` |
| Diary (§3) | `concept_shopping`, `theme_work_deadlines`, `diary_sentiment_mean`, `entity_mom` |
| Context spans | `span_vacation`, `span_sick` |
| Outside sources (§2.5) | `weather_temp_max`, `weather_pressure_change_24h`, `air_aqi`, `daylight_h`, `holiday` |

**Missing is not zero.** A day with no coffee *logged* is only "0 cups" if the
day was **reviewed** (or the tracker is marked "always logged"). Otherwise
it's unknown. This one rule removes the biggest bias in self-tracking data
(`tagging-and-daily-review.md` §6.1).

### 4.2 Day-level relationships

For each pair of features with enough support, at lags 0 and ±1 day:

| Pair | Method | Reported as |
|---|---|---|
| continuous ↔ continuous | Spearman on residuals (weekday profile + slow trend removed) | "higher X goes with higher Y" |
| yes/no ↔ continuous | Mann-Whitney + Cliff's delta + median shift in real units | "on days with X, Y is 34 min shorter" |
| yes/no ↔ yes/no | odds ratio (Fisher's exact test) | "X days are 2.4× as likely to have Y" |
| time of day ↔ continuous | as continuous, on minutes-after-wake | "earlier lunch goes with higher productivity" |

Then: Benjamini-Hochberg FDR across *all* tests, an effect-size floor, and
minimum support (e.g. ≥ 8 days per group).

**Direction (lags).** The ±1-day lags are what answer *"does sleep make the
family situation worse?"*. Compare sleep(t) → family friction(t+1) with
family friction(t) → sleep(t+1). An asymmetry is a **hint** of direction,
not proof, and the wording reflects that ("tends to follow").

**Longer, spread-out lags: distributed lag models.** Some effects arrive
days later and are spread over several days: *does rain on Monday make you
sad or unproductive on Wednesday?* Testing each lag separately fails for
three reasons:
- **Exposures come in streaks.** Rainy Mondays sit in rainy weeks, so a
  naive "Monday rain → Wednesday mood" link is often just Wednesday's own
  rain.
- **Lags × features multiplies the false hits.**
- **Effects are often curved and smeared.** A little rain does nothing, a
  lot does something, and the effect is spread over days 1–3.

For exposures that are measured every day (weather, air quality, daylight,
sleep, caffeine, workload) the engine fits **distributed lag models**, the
standard method environmental epidemiology uses for questions like "heat →
hospital admissions over the following days". A distributed lag model
estimates one smooth effect curve over lags 0…N (e.g. 7 days) **while
controlling for the exposure on all the other days**. The non-linear variant
(DLNM) also lets the dose-response bend. Weekday profile and slow trend are
removed first, as everywhere else. The output is a curve that becomes a
sentence:

> *"Heavy-rain days (> 10 mm) are followed by lower mood, strongest **2
> days later** (−0.4 on a 1–5 scale), fading by day 4. 212 days, moderate."*

Guardrails: few parameters (a smooth lag curve, not one coefficient per
day); one model per exposure–outcome pair, counted as **one** test in the
FDR, not N; it needs months of daily data (a full season of weather variety
helps), so it runs only once that exists; and it's reported as association,
not cause.

### 4.3 Within-day relationships (timestamped events)

"Does coffee make you active?" is a question about the **hours after** the
coffee, not about the day. For any timestamped tracker or moment:

- **Event-locked response.** Average a HealthLog signal (steps, heart rate,
  stress proxy) over e.g. −60…+180 min around each event, minus a
  **matched control**: the same clock time on days without the event, which
  takes care of the normal daily rhythm.
  - *Result:* "after coffee, steps are +40% for ~90 min, then back to normal."
- **Event → event.** Is `anxiety` logged within 3 h after
  `concept_shopping` entries more often than at other times of day? That's a
  rate ratio against time-matched baseline windows.

This uses minute-level data HealthLog already stores (`metric_samples`,
`stress_intraday`), read-only.

### 4.4 Confounders and context

- **Spans** (sick, travel, vacation) are excluded by default from other
  tests, and reported as their own effects.
- **Adjusted check for the top insights.** Re-test each top insight
  controlling for the most common confounders (sleep, weekday, workday vs
  weekend) with a small regression. Insights that vanish get demoted or
  annotated ("mostly explained by sleep").

### 4.5 Experiments (n-of-1)

Correlations suggest; experiments test. The user can start an experiment
(*"no coffee after noon for 14 days"*). The app tracks adherence and compares
the outcome trackers to a baseline period (with the same confounder checks),
then reports: *"bedtime 22 min earlier; sleep efficiency unchanged."* For a
lifestyle learning app this is the most valuable feature beyond plain
correlations, and it's cheap once the feature table exists.

### 4.6 Insight output

Each insight is stored with its numbers **and** a sentence, generated from
templates per method and tracker type (with polarity deciding "better" vs
"worse"):

- *"On days with **3+ cups of coffee**, you take **18% more steps**. 46 days, strong."*
- *"**Family friction** is more likely the day **after < 6 h sleep**
  (31% vs 11% of days). 64 days, moderate. Sleep tends to come first."*
- *"Days with **shopping** entries have **higher anxiety** (median 3 vs 2).
  14 vs 61 days, moderate. [show entries]"*
- *"When **first social-media use** is within 30 minutes of waking,
  **productivity** that day is lower (3.1 vs 3.6). 28 days, weak."*

Plus **descriptive insights** that need no significance test: weekday
profiles, streaks, personal bests, 30-day vs previous-30-day changes, "you
haven't logged X in 9 days". HealthLog's own findings are shown alongside as
cards. Optionally, the local LLM writes a weekly narrative from the insight
rows (numbers only, never raw diary text unless the user opts in).

### 4.7 Beyond correlations: ML models

Pairwise relationships answer "does X go with Y?". Models answer
"what, *together*, drives Y?" and "what kind of day is this?":

- **Next-day prediction with explanations.** Predict tomorrow's mood,
  productivity, sleep or HRV from today's features (gradient-boosted trees
  or regularised regression). The point isn't the forecast; it's **feature
  importance** (permutation importance or SHAP values), turned into
  sentences: *"the biggest drivers of your next-day productivity are sleep
  duration, caffeine after noon and pressure drops"*.
- **Day types.** Cluster days on their full feature profile ("recovery
  days", "stress days", "social days") and describe what each type looks
  like and what tends to precede it.
- **Change points.** Detect when a metric's level shifted (a new baseline
  after starting a medication, moving, a new job) and mark it as a timeline
  event that later analysis can condition on.
- **Multivariate anomalies.** Days that are unusual *as a whole*, even when no
  single metric is extreme.

Guardrails, because personal data is small (hundreds of days, not millions):
- **Time-ordered cross-validation only** (train on the past, test on the
  future), never random splits, which leak information.
- **Simple, regularised models** first, and always compared with a naive
  baseline ("tomorrow = recent average"). A model that doesn't beat the
  baseline isn't reported.
- **Importance is not causation**; the wording says "goes with", not "causes".
- **Minimum history** before any model runs (e.g. 90 days), shown in the UI
  as progress rather than as silence.

---

## 5. Input: making logging nearly free

Flexibility is useless if logging is tedious, so the input design matters as
much as the analysis. **Every capture path is structured:** values come from
menus and typed prompts, the time is recorded automatically, and nothing is
interpreted by a language model.

### 5.1 Two homes for data

- **Things Apple Health can model** (caffeine, alcohol, water, symptoms,
  mindful minutes, State of Mind) are logged **into Apple Health** with the
  built-in Shortcuts action **"Log Health Sample"**, or in the Health app or
  on the Watch. They work offline, need no server, and arrive through
  HealthLog's normal pipeline. The docs ship ready-made recipes.
- **Everything else** (custom scales like productivity, time-of-day trackers,
  choices, spans, moments with causes, diary) goes to the companion's API.

### 5.2 The generic "Track" Shortcut (one Shortcut for all trackers)

The *set of tracker types* is fixed in code (§2.1), even though trackers
themselves are unlimited. So one Shortcut handles every tracker by
branching on type:

```
"Hey Siri, track"
 → fetch tracker list (favourites first; cached in iCloud Drive, refreshed occasionally)
 → Choose from List (spoken or tapped): Coffee / Social media / Productivity / Anger / …
 → ask only what the type needs:
     count  → "How many?" (default 1)      scale → "Rate 1 to 5"
     check  → "Yes or no?"                  moment → "How strong, 1–3?" (optional)
     choice → Choose from List of options   time  → now, or "earlier?" → time picker
 → POST {tracker, value, time}  →  reply "Logged Social media at 07:10"
```

- **"First use" is derived, not logged.** Log `social_media` each time; the
  server computes first time, last time and count per day (§2.1). The
  Shortcut only ever sends *now*, or a picked time.
- **Shipped once as an iCloud link with import questions** (server URL, API
  token), asked once at install. Apple requires Shortcut files to be signed
  (on a Mac signed into iCloud), so the server can't generate per-tracker
  Shortcuts. One shared generic Shortcut avoids that entirely.
- **One-word Siri phrases for favourites** are tiny stubs the user creates
  in about 30 seconds: a Shortcut named "Coffee" containing *Run Shortcut
  "Track"* with input `coffee`. Siri phrases are Shortcut names, and Siri
  can't pass the rest of a sentence as input, so this is the closest to
  one-breath logging without a native app.
- **Fast and failure-visible.** The API answers in well under a second. If
  the server can't be reached, the Shortcut says "Not saved" so the entry is
  re-logged (Shortcuts can't queue offline; the PWA and Apple Health paths can).

### 5.3 Per-tracker URLs and scoped tokens

Creating a tracker instantly gives it its own endpoint,
`POST /api/log/{tracker_key}` (one generic route, no code generated), and
optionally its **own token that can only log that tracker**. A leaked coffee
link can log coffee, but it can't read data or touch other trackers. That
makes every tracker usable from **any** HTTP client:

- the generic Shortcut or a one-word stub;
- **NFC stickers** (an iOS automation runs on tap, e.g. on the coffee machine);
- Home Assistant buttons, a Stream Deck key, a curl one-liner.

Each tracker's page in the PWA has a **Set up** panel:
1. the URL and scoped token, each with a copy button (and token revocation);
2. **Add to Siri**: three short steps to create the stub, with copyable values;
3. a **Test** button that opens
   `shortcuts://run-shortcut?name=Track&input=text&text=<key>`, to check it
   works before naming it for Siri.

The PWA can't install Shortcuts itself (Apple doesn't allow it); a native
iOS app using App Intents is the only way to remove the manual Siri step,
and is an option for later.

### 5.4 The PWA and the rest

- **PWA (installable web app).** A **Today** screen (quick-add buttons for
  pinned trackers, what's logged so far), a **daily review** (every tracker
  with `in_review: true`, generated from tracker types), the diary, and
  back-dating ("at 11:35 …"). It works offline: entries queue on the device
  with a device-generated id and sync later, and retries never create
  duplicates.
- **Reminders.** Per-tracker or review reminders through web push (iOS
  supports it for Home Screen web apps) or HealthLog's existing Gotify /
  PushBits notifications.
- **Imports.** Apple State of Mind is already in HealthLog's raw archive and
  is read from there (no upstream change). It maps onto trackers ("angry" →
  a moment, associations → causes). CSV import covers history from other
  apps.

---

## 6. Screens

| Screen | Purpose |
|---|---|
| **Today** | quick-add, today's values (yours + HealthLog's), what's still unlogged |
| **Review** | the evening pass: fill gaps, edit/delete, a short diary entry, mark the day reviewed |
| **Insights** | ranked feed of sentences, each with an "explain" view (numbers, method, evidence, entries) |
| **Trackers** | create / edit / archive trackers; per tracker: history, weekday profile, related insights |
| **Diary** | entries, search (by text or by meaning), concepts & themes management |
| **Experiments** | start, track adherence, results |
| **Health** | HealthLog findings and key metrics as cards (Grafana stays available for deep dives) |

---

## 7. Data model (schema `companion`)

```sql
trackers        (id, key UNIQUE, name, type, unit, scale JSONB, aggregation, timestamped,
                 polarity, category, aliases TEXT[], prompt JSONB,
                 archived BOOL, successor_id, created_at)
events          (seq BIGSERIAL PK, received_at, client_id UUID, op TEXT,       -- append-only log:
                 payload JSONB, source TEXT)                                   -- source of truth
observations    (client_id UUID PK, tracker_id, observed_at TIMESTAMPTZ, day DATE,
                 value_num DOUBLE PRECISION, value_text TEXT, value_json JSONB, -- one typed value
                 source TEXT, deleted BOOL)
spans           (client_id UUID PK, tracker_id, start_day, end_day, deleted BOOL)
api_tokens      (id, name, token_hash, scope TEXT,                    -- 'all' | 'read' | 'log:<tracker_key>'
                 created_at, last_used_at, revoked_at)                -- per device / per tracker, revocable
source_cache    (source TEXT, day DATE, hour SMALLINT, feature TEXT,  -- outside data (§2.5),
                 value DOUBLE PRECISION, fetched_at,                  -- fetched once per day
                 PRIMARY KEY (source, day, hour, feature))
models          (id, target TEXT, trained_at, method TEXT,            -- ML runs (§4.7): scores vs the
                 cv_score, baseline_score, importances JSONB)         -- naive baseline, importances
day_reviews     (day DATE PK, completed_at)
diary_entries   (client_id UUID PK, written_at, day, text, source, deleted BOOL)
diary_vectors   (entry_id, model TEXT, embedding vector(N), PRIMARY KEY (entry_id, model))
diary_extracts  (entry_id, model, entities JSONB, sentiment REAL)
concepts        (id, name, seeds TEXT[], threshold REAL, kind TEXT)            -- 'concept' | 'theme'
concept_hits    (entry_id, concept_id, score REAL)
daily_features  (day, feature TEXT, value DOUBLE PRECISION, PRIMARY KEY (day, feature))  -- rebuilt nightly
insights        (id, computed_at, kind, feature_a, feature_b, lag, method, effect,
                 p_adj, n_a, n_b, sentence TEXT, details JSONB, evidence JSONB)
experiments     (id, name, hypothesis, intervention JSONB, outcome_features TEXT[],
                 baseline_start, start_day, end_day, status, result JSONB)
```

- `observations` uses **one table for every tracker type**: the type lives on
  the tracker, and the app validates values against it. That's the right
  trade-off at personal scale (tens of rows a day). Per-tracker tables would
  need a migration per tracker, which is exactly what §1 rules out.
- `events` is the append-only log, and every other table can be rebuilt from
  it. That mirrors HealthLog's raw archive: nothing is lost, and fixes are
  re-derivations, not data surgery. Deletes are tombstone events.
- `daily_features` is a **cache**, fully rebuilt by the nightly job, so new
  feature definitions apply to all history automatically.

---

## 8. Architecture and coexistence with upstream

### 8.1 Deployment

```
iPhone / Watch ── HAE ─────────────► healthlog (upstream image, untouched)
       │                                    │ writes schema public
       └─ Log Shortcut / PWA ─► companion (our container: API + PWA + nightly jobs)
                                            │ writes schema companion, READS public
                         healthlog-db (one Postgres/TimescaleDB instance)
```

**Hosting-agnostic.** The companion serves plain HTTP and contains no code
for any specific hosting setup. TLS, the public name and network reach are
the job of whatever sits in front: nginx, Caddy, Traefik, Tailscale Serve, a
Cloudflare Tunnel or a VPN. The only hard requirement is **HTTPS**, because a
PWA (service worker, install, web push) needs a secure context. Forwarded
headers (`X-Forwarded-Proto/For`) are honoured only from `TRUSTED_PROXIES`,
the same setting and semantics HealthLog already uses.

**Authentication is the one part that must be coded**, as two generic modes
selected by config (no provider-specific code):

| Mode | How | Fits |
|---|---|---|
| `password` *(default)* | single-user password (hashed) → session cookie for the PWA; per-device API tokens (`COMPANION_TOKEN`s, revocable) for Shortcuts | anything, including a bare nginx/Caddy with no auth of its own |
| `proxy_header` | trust a configurable identity header (e.g. `Remote-User`, `X-Forwarded-User`, `Tailscale-User-Login`), **only** from `TRUSTED_PROXIES`, matched against an allow-list | proxies that already authenticate: Tailscale Serve, Authelia, Authentik, oauth2-proxy, Cloudflare Access |

API tokens work in both modes, because Shortcuts can't do interactive login.
Tokens are **scoped** (full access, read-only, or log-only for a single
tracker; §5.3), stored hashed, and revocable one at a time.
HealthLog's `INGEST_SECRET` is never used.

**Deployment recipes are documentation, not code**: a short README section
with tested examples (Tailscale Serve; nginx or Caddy + `password` mode;
Authelia + `proxy_header` mode).

### 8.2 Code layout: a separate directory in the fork

```
healthlog-ml/   (fork)
├── backend/ grafana/ docs/ docker-compose.yml   ← upstream-owned; never edited here
├── companion/  (app/, migrations/, web/, tests/, Dockerfile)   ← ours
└── compose.companion.yml                        ← ours, layered via `-f`
```

Syncing is `git fetch upstream && git merge upstream/main`, which is always
clean because nothing overlaps. Changes HealthLog itself needs go upstream as
PRs (like #104). *Housekeeping first:* the local Grafana service currently
lives in upstream's `docker-compose.yml`; move it to the override file.

**Relationship to upstream: the fork is the product.** We asked first
([issue #107](https://github.com/anym001/healthlog/issues/107)). The
maintainer welcomes ingest-level PRs (State of Mind parsing, registry
entries), would keep analysis changes under his review, and suggested a
frontend-only companion that stores its data in HealthLog. His suggested
order is effectively a map of what HealthLog lacks for manual data (storage,
a read API, auth for apps, sub-daily analysis). Our goals (a multi-timeframe
analysis engine, outside data sources, ML models and our own UI, at our own
pace) go beyond that scope, so:

- **We build in this fork, in parallel with upstream.** The companion is our
  engine, schema and UI, in `companion/`. HealthLog is the data pipeline we
  build on. No separate repository.
- **A light fork by default.** Upstream's `backend/` stays untouched, so their
  releases merge cleanly and their fixes reach us for free. When we *need*
  a `backend/` change we make it, and anything useful to them goes upstream
  as a PR too, so it comes back through their releases. If the directions
  drift too far apart, we can stop syncing at any time.
- **Ingest-level work goes upstream** because we depend on that layer too.
  The rule: *getting Apple Health data in correctly is upstream; what the
  data means is ours.* Tracked in [`roadmap.md`](roadmap.md).
- **Exit plan**: HealthLog's part (parsing Health Auto Export payloads) is
  the simplest part, and the raw exports are in the nightly backup, so the
  companion could ingest directly and rebuild everything if ever needed.
- **Licence**: HealthLog is AGPL-3.0, which allows all of this. Running it
  for yourself carries no obligations; offering it to others (including as a
  hosted service) means sharing the source under the AGPL. Code in
  `companion/` that copies no HealthLog code and only reads the database
  can arguably be licensed separately, but because it lives in the same
  repository, the simplest course is to treat the whole fork as AGPL.
  (Not legal advice.)

We follow upstream's conventions (`CONTRIBUTING.md`: English, ruff with line
length 120, pytest, Alembic-only schema), both for consistency and so any
piece can become a PR without rework. The companion image has its own build
workflow (`.github/workflows/companion.yml`), a new file, so it can't conflict.

**No git submodule.** The companion couples to HealthLog through the
**database and compose file, not imports**, so a submodule would add clone
friction and pinned-commit drift for no benefit.

### 8.3 Database isolation (the critical part)

Upstream's migrations routinely **drop and recreate their own objects**:
`findings_feed` in 0020 and 0021, `daily_metrics`, `sleep_metrics`,
`sleep_nightly`, and `raw_ingest` itself in 0016. A view, foreign key or
SQL-body function of ours that depended on one of those would make Postgres
refuse their `DROP`, so **their upgrade would fail on our machine**.

- **Same instance, own schema `companion`, own role `companion`.** The role
  owns its schema and has `SELECT`-only on `public`, so Postgres itself
  enforces that our code can't modify upstream data. The role, grants and
  `CREATE EXTENSION vector SCHEMA companion` go in a one-time bootstrap
  script, not in an upstream migration.
- **Own Alembic history** (`version_table_schema="companion"`).
- **No dependent objects**: no views over `public.*`, no foreign keys into
  it. Cross-schema reads happen in application queries only, against base
  tables (not upstream's views, which they rebuild most often).
- **Read contract**: one module lists every upstream table and column we
  read; `companion check-upstream` verifies them at startup and after each
  upgrade. A rename degrades one feature with a clear message instead of
  breaking anything.
- **Backups**: the nightly `backup.sh` already dumps the whole database and
  all roles, so the new schema, role and vectors are covered.

### 8.4 Code reuse

The Companion has its own stats code (scipy, statsmodels, scikit-learn) and
**reuses HealthLog's methodology, not its internal Python modules**
(residual Spearman, lags, FDR; ARCHITECTURE §4.8, §11). Importing upstream
internals would tie us to functions they're free to refactor.

---

## 9. Statistical caveats, in the app and in the docs

- **Self-report is biased.** People log more on bad days, and logging changes
  behaviour. The reviewed-day rule (§4.1) and prompted capture reduce this;
  they don't remove it.
- **Many features means many false hits.** FDR plus minimum support plus effect
  floors, and text-derived features only once they have enough days.
- **Small n early.** Most insights need 6–8 weeks of consistent logging; the
  app should say so rather than show noise.
- **Correlation ≠ causation**, with lags as hints only. Experiments (§4.5)
  are the way to test.
- **Health decisions** belong with a clinician. The app's job is to make
  patterns and evidence easy to bring to one.

---

## 10. Roadmap

See [`roadmap.md`](roadmap.md): two parallel tracks, upstream contributions
(Track A) and our product (Track B: skeleton, more Health metrics, custom
tracking, outside data sources, the multi-timeframe engine, ML models,
diary, experiments, imports, polish).

## 11. Decisions

Decided:

- **The fork is the product**: `companion/` in this fork, built in parallel
  with upstream; a light fork by default; ingest-level work offered upstream
  as PRs; no separate repository, no submodule (§8.2).
- **Hosting**: hosting-agnostic; generic `password` / `proxy_header` auth
  modes plus scoped API tokens; deployment recipes documented, not coded (§8.1).
- **Capture**: structured only; Apple Health for what it can model; one
  generic Track Shortcut; per-tracker URLs and scoped tokens; no language
  model in capture (§5).
- **Outside data**: opt-in, fetch-only, coarse fixed location; weather first (§2.5).

Open:

1. **Embeddings**: model inside the companion container (recommended:
   keeps diary text on the server) or the Ollama host?
2. **Front end**: server-rendered HTMX (recommended: no build step) or a JS
   framework?
3. **Day boundary**: what hour does a "day" end (default 04:00)?
4. **Outside-data policy**: *fetch-only* (recommended: one batched daily
   request for a coarse area, e.g. Open-Meteo, key-less, with historical
   backfill) or *strict offline* (local weather station / Home Assistant
   only)? A weather request reveals only a rough location and when the
   server asks; no health or personal data is ever sent.
5. **Name**: "Companion" is a placeholder.
