# Tags, moments & a daily review: design notes

How to record subjective context through the day ("Hey Siri, track: high
anxiety"), review the day in the evening, and feed both into the analysis so
HealthLog can say things like *"on days you tag `family-conflict`, your HRV the
next morning is lower"* or *"your stress proxy agrees with your anxiety taps
70% of the time"*.

This builds on [`webapp-ingest-analysis.md`](webapp-ingest-analysis.md), which
covers the auth and pipeline side of a data-entry app. This document covers
what to capture, how to store it, how to correlate it, and the order to build
it in.

---

## 1. What we want to capture

Three different shapes of data, which need different storage and statistics:

| Shape | Examples | When | Statistical form |
|---|---|---|---|
| **Moment** (point event, optional intensity) | "high anxiety", "argument", "coffee", "panic", "great conversation" | any time, one tap or one sentence | event timestamp → daily count / max intensity; intraday event-locked analysis |
| **Day rating / habit** (one value per day) | mood 1–5, energy, stress, "alcohol? y/n", "meditated?", "outside > 30 min?" | the evening review | a numeric daily series, the same kind the analysis already uses |
| **Context span** (interval, days long) | vacation, sick, travel, deadline week, family visiting | set once, ends later | a covariate or exclusion mask, not a "metric" |

The distinction matters most for **correlation**: a moment tag is sparse and
binary-ish, a day rating is a normal series, and a context span is a confounder
that should *condition* other findings ("HRV is down, but you're sick").

---

## 2. Something already flowing in: Apple State of Mind

Before building anything: **iOS 18 / watchOS 11 "State of Mind" logging already
reaches HealthLog** through Health Auto Export, but the parser drops it.

Each Health Auto Export payload carries these entries under
`data.stateOfMind` (illustrative example):

```json
{
  "kind": "momentary_emotion",              // or "daily_mood"
  "valence": -0.61,                          // -1 … +1 (continuous)
  "valenceClassification": "unpleasant",    // very_unpleasant … very_pleasant
  "labels": ["anxious", "stressed"],         // Apple's fixed emotion vocabulary
  "associations": ["family", "work"],        // Apple's fixed "what's affecting you"
  "start": "2026-01-01T20:30:00Z", "end": "...", "id": "<UUID>"
}
```

Apple's label vocabulary covers emotions such as *angry, stressed, anxious,
frustrated, worried, calm, content, overwhelmed …*, and the associations include
*family, work, health, money, friends, fitness, travel, self_care …*. That covers much of the
"stress, family, happiness, moods" wish list, with:

- **Native capture on the Watch** (Mindfulness app → State of Mind), the phone,
  and the Health app, with no server reachability needed.
- **Offline-safe**: it lands in HealthKit first and arrives with the next HAE sync.
- **A stable id** per entry (`id`), so upserts are idempotent.
- **Retroactive**: every payload is archived verbatim in `raw_ingest`, so once
  a parser exists, a re-derive pass (modelled on `rederive-workout-hr`)
  recovers all State of Mind history already sent.

**Its limits** are a fixed Apple vocabulary (no "coffee", "vacation",
"migraine", "argument with X"), no free text through HAE, and no custom
intensity. So it's the **mood and emotion backbone**, not the whole answer.
Custom tags still need our own path (§3).

> **Recommendation:** parse State of Mind first. It's the cheapest win, it's
> backfilled for free from the archive, and it gives a real numeric daily
> series (mean/min valence) on day one.

---

## 3. Capture paths for custom tags

### 3a. "Hey Siri, …" via an iOS Shortcut (no app needed)

A Shortcut named **"Track"** (the Siri phrase is the Shortcut's name):

1. **Dictate Text** (or *Ask for Input* on the Watch). Siri asks "What?",
   you say "high anxiety".
2. **Get Contents of URL** → `POST https://<host>/api/journal`
   - header `X-Journal-Token: <journal secret>`
   - JSON body `{"text": <Dictated Text>, "time": <Current Date, ISO 8601>, "source": "siri"}`
3. **Speak / Show Result** of the server's reply ("Logged *anxiety*, high").
   Echoing the parsed tag back catches dictation errors immediately.

Honest constraints:

- **It takes two steps, not one breath.** A Shortcut can't take the words
  after its name as input, so "Hey Siri, track high anxiety" in one sentence
  doesn't work. You get "Hey Siri, track" → "What?" → "high anxiety". Doing it
  in one breath needs a native app with App Intents (parameterised App
  Shortcuts), which is out of scope here.
- **Quick-pick variants** avoid dictation errors. A second Shortcut,
  "Quick tag", can use *Choose from List* (anxiety, coffee, alcohol,
  argument, headache, …) plus an optional intensity, for a Watch complication
  or the Action button.
- **Reachability:** the Shortcut needs network access to the server. With
  Tailscale on the iPhone, a `*.ts.net` URL works on the phone. **To verify:**
  whether a Watch-run Shortcut's request goes through the paired iPhone's
  Tailscale tunnel, or needs a publicly reachable endpoint. If it doesn't, the
  Watch fallback is State of Mind (§2), which never needs the network at log
  time.
- **Offline:** a failed request is simply lost (Shortcuts has no retry
  queue). Have the Shortcut show an error so you re-log, or make the PWA (§5)
  the offline-capable path.

### 3b. Server-side text → tag normalisation

Keep the **raw text verbatim** and derive structured fields from it, so the
mapping can be improved later and re-run over history:

```
"high anxiety"            → tag=anxiety,  intensity=3 (high)
"bit anxious"             → tag=anxiety,  intensity=1
"had two coffees"         → tag=caffeine, count=2
"fight with mom"          → tag=family-conflict
"vacation starts"         → context span: vacation (open-ended)
```

Do it in two tiers:

1. **Deterministic first**: a tag vocabulary table with aliases
   (`anxious|anxiety|panicky → anxiety`) and intensity words
   (`slight|bit|mild → 1`, `—|moderate → 2`, `high|very|really → 3`).
   Deterministic, testable, instant.
2. **Local LLM fallback** for text the vocabulary doesn't match. Ollama is
   already part of the stack (`narrate/client.py`). Ask it to map to an
   *existing* tag or propose a new one; new proposals land as
   `unreviewed`, never auto-trusted. Nothing leaves the box.

Unmatched text is kept as a **note** (still searchable, shown in the review),
not dropped.

### 3c. Works today, with zero code (stopgap)

Because ingest is metric-agnostic, a Shortcut can post an HAE-shaped body to
the existing `/api/ingest` with the existing token right now:

```json
{"data":{"metrics":[{"name":"tag_anxiety","units":"level","data":[
  {"date":"2026-10-15 14:02:00 -0400","qty":3,"source":"siri"}]}]}}
```

It lands in `metric_samples`, shows up in Grafana, and gets auto-registered.
**But it won't reach the correlation pass**: `core_metrics()` reads the
*code* registry (`registry.py`), and auto-registered metrics are
`secondary`. It also loses free text, can't delete, and puts the all-powerful
ingest token on the phone. That's fine for collecting data while the real
thing is built, since those rows can be migrated later.

---

## 4. Data model

The existing principle (ARCHITECTURE §4.0) is "metrics are data, not
schema", with sleep and workouts as the only special cases with their own
tables. Journal entries are a third special case: they carry text, they can be
edited and deleted, and they have intervals. Forcing them into
`metric_samples` would lose all three.

### 4a. Keep the raw-archive invariant

Every journal write still goes through `ingest_bytes`, as a new top-level key
in an HAE-shaped envelope:

```json
{"data": {"journal": [
  {"client_id": "b1e4…", "op": "upsert", "time": "2026-10-15T14:02:00-04:00",
   "text": "high anxiety", "source": "siri"}
]}}
```

`parse_payload` already ignores unknown keys, so this is additive. You get
content-hash dedup, a verbatim archive and re-derive for free. **Deletes are
tombstones** (`"op": "delete", "client_id": …`) archived like everything else,
so replaying the archive reproduces deletions instead of resurrecting the
entries (this solves the "no delete path" problem raised in
`webapp-ingest-analysis.md` §3).

### 4b. Tables (one migration)

```sql
journal_entries (
  client_id    UUID PRIMARY KEY,          -- generated on the device; idempotent retries
  time         TIMESTAMPTZ NOT NULL,      -- when it happened (editable), not when it was sent
  end_time     TIMESTAMPTZ,               -- set for context spans
  kind         TEXT NOT NULL,             -- moment | rating | habit | context | note
  tag          TEXT REFERENCES tag_vocabulary(tag),   -- NULL for an unmatched note
  value        DOUBLE PRECISION,          -- intensity 1-3, rating 1-5, habit 0/1, count
  text         TEXT,                      -- raw input, verbatim
  source       TEXT,                      -- siri | watch | pwa | review | state_of_mind
  deleted      BOOLEAN NOT NULL DEFAULT false,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

tag_vocabulary (
  tag          TEXT PRIMARY KEY,          -- anxiety, caffeine, family-conflict, vacation …
  kind         TEXT NOT NULL,             -- moment | rating | habit | context
  category     TEXT,                      -- mood | social | substance | food | health | context
  polarity     SMALLINT,                  -- -1 / 0 / +1, for narration wording only
  aliases      TEXT[],                    -- deterministic matching (§3b)
  status       TEXT DEFAULT 'active'      -- active | unreviewed (LLM-proposed) | retired
);

day_reviews (
  day          DATE PRIMARY KEY,          -- local day (same TZ rule as the daily grid)
  completed_at TIMESTAMPTZ               -- "this day was reviewed", see §6.1
);

state_of_mind (                           -- parsed from HAE, §2
  hae_id UUID PRIMARY KEY, time TIMESTAMPTZ, kind TEXT, valence DOUBLE PRECISION,
  classification TEXT, labels TEXT[], associations TEXT[]
);
```

Like the metric registry, the vocabulary is **data**: adding "migraine" is a
row, not a deploy. Seed it in a migration with a starter set, including
Apple's labels and associations, so State of Mind and custom tags share one
namespace (`family` the association and `family` your tag are the same thing
to the analysis).

### 4c. Daily features (what the analysis sees)

A loader in `analysis/load.py` turns entries into daily series on the
existing local-day grid:

| Series | Definition |
|---|---|
| `mood_valence_mean`, `mood_valence_min` | from `state_of_mind` (+ PWA rating if present) |
| `rating_<tag>` | the evening rating, e.g. `rating_mood`, `rating_energy` |
| `tag_<tag>` | max intensity that day (0 if the day was **reviewed** and it wasn't tagged; NaN otherwise) |
| `habit_<tag>` | 0/1 from the review checklist |
| `context_<tag>` | 0/1 mask from spans (vacation, sick, travel) |

---

## 5. The daily review (PWA)

### What it shows

An evening screen, about 60 seconds to complete:

1. **Today's moments**: everything tagged today (Siri, Watch, State of
   Mind), editable and deletable. Fixes dictation errors and back-fills
   forgotten ones ("I didn't log the coffee").
2. **Ratings**: mood, energy and stress as 1–5 sliders. Keep it to three to
   five; more ratings means fewer completed reviews.
3. **Habit checklist**: configurable yes/no (alcohol, caffeine after 2 pm,
   meditated, outside 30 min, screens in bed, social time).
4. **Context**: start or end a span (vacation, sick, travel).
5. **Note**: free text.
6. **What the body said**: today's sleep, HRV vs baseline, stress profile,
   Body Battery low, from existing tables. Showing it *after* the ratings
   avoids anchoring your self-report on the numbers.

Submitting marks the day reviewed (`day_reviews`), which matters for the
statistics (§6.1).

### How it's built and served

- **Same FastAPI app**: a `routers/journal.py` (+ `StaticFiles` for the PWA)
  so there's no CORS and one deployable. A plain HTML + small JS bundle is
  enough; no framework is needed for five form sections.
- **PWA basics**: manifest + service worker, installable to the Home Screen.
  Entries are written to IndexedDB first with a client-generated `client_id`,
  then synced, so it works on a flaky connection and retries are idempotent.
- **Tailscale** fits this well:
  - `tailscale serve` gives the app an HTTPS `https://<machine>.<tailnet>.ts.net`
    URL with a real certificate. Service workers require a secure context, so
    this matters for a PWA.
  - **Auth from identity, not a password:** Tailscale Serve adds
    `Tailscale-User-Login` headers to proxied requests. The journal router can
    accept a request only when it arrives from the local Serve proxy
    (loopback) **and** carries an allow-listed login. There's no token in the
    browser at all.
  - Nothing is exposed to the internet; HAE and Siri can use the same tailnet URL.
- **Alternative** if a non-tailnet path is needed (e.g. the Watch, §3a): a
  separate `JOURNAL_SECRET` for the Shortcut, behind the existing TLS reverse
  proxy, scoped to `/api/journal` only, never the HAE token.

Docs impact (per `CLAUDE.md`): new env vars (`JOURNAL_SECRET`, an
allow-listed Tailscale login) → `README.md`; the new table, ingestion path and
finding kind → `docs/ARCHITECTURE.md` (new §4.11 and an amended §5).

---

## 6. How tags become findings

The existing correlation pass is **Spearman on STL residuals with lags 0–3,
FDR-corrected** (ARCHITECTURE §4.8). That's right for continuous daily series
like `mood_valence_mean` or `rating_energy`: add them to the analysed set and
they flow through unchanged. It's the **wrong tool for sparse tags**, though:
STL on a mostly-zero 0/1 series is meaningless, and Spearman on it collapses
into a rank comparison anyway. Tags need their own finding kind.

### 6.1 The missing-data trap (why the review matters)

"No `anxiety` tag today" means two different things: *I wasn't anxious*, or
*I didn't log anything*. Treating every untagged day as a 0 makes days you
forgot to log look like calm days, which biases every tag effect toward zero.

The review completion flag resolves it: **on a reviewed day, an absent tag
is a real 0; on an unreviewed day it is NaN**. All tag statistics run only on
reviewed days. This is the single most important reason to build the daily
review, beyond convenience.

**Removing never deletes.** Taking a tag off the list, or archiving a
tracker, only stops it being offered. Its entries stay in the event log and
in the analysis: a removed tag keeps its own feature ("… (removed)"), and
the zeros of both stop at their last entry, since a review that no longer
shows them says nothing about them. Deleting the entries themselves is a
separate, explicit **purge** (plan M11, not built yet).

### 6.2 New finding kind: `tag_effect`

For each tag with enough support (e.g. ≥ 8 tagged and ≥ 8 untagged reviewed
days) and each outcome series, at lags 0 and +1 day:

- **Both directions**:
  - tag → body: `alcohol` → next-morning HRV, sleep efficiency, resting HR.
  - body → tag: short sleep → `anxiety` tagged the next day.
- **Compare** outcome values on tagged vs untagged reviewed days with
  **Mann-Whitney U**, effect size as **Cliff's delta** (rank-based, like the
  existing Spearman), plus the **Hodges-Lehmann shift** in real units ("HRV
  −6 ms").
- **Remove weekday effects first**: compare residuals after subtracting the
  weekday profile, so a tag that only happens on Mondays doesn't inherit
  Monday's physiology.
- **Context spans as exclusion**: drop `sick`/`travel` days by default, and
  report `vacation` as its own effect rather than letting it confound
  everything.
- **FDR** across tags × outcomes × lags, like the existing pass. Tags multiply
  the number of tests fast, so this isn't optional.
- Stored as a `findings` row:
  `kind='tag_effect', metric_a=tag_<x>, metric_b=<outcome>, lag_days,
  coefficient=cliffs_delta, details={hl_shift, n_tagged, n_untagged}`. That
  way Grafana, `findings_history` and the narration pick it up with no
  special casing. The math goes in `analysis/pure.py` as DB-free helpers,
  tested against synthetic series with a planted effect, per project
  convention.

### 6.3 Intraday: do moments agree with the stress proxy?

`stress_intraday` already has a minute-level stress timeline. Moments have
exact timestamps, so you can do **event-locked averaging**: the mean stress
in the ±60 min around each `anxiety` tap, compared with the same hour of day
on reviewed days without one. That gives:

- **Validation of the stress proxy** against your own subjective report. Is
  the HR/HRV-based proxy measuring what you feel?
- **Physiology vs perception**: tags where the body reacts but you don't
  feel it, or the reverse.

This is a descriptive `tag_intraday` finding, and a very good Grafana panel.

### 6.4 Grafana without new code

Moments and spans become **Grafana annotations** with a plain SQL annotation
query on `journal_entries`, overlaid on the existing HRV, stress and sleep
panels. Seeing "argument" pinned on the stress timeline is half the value,
before any statistics.

### 6.5 Narration

The narration context gets a `_section_tag_effects` builder like the other
kinds. Pass **tag names and statistics only**, never note text, by default.
`scrub_details()` is the single pass-through point already designated for
that.

---

## 7. Methodological pitfalls specific to self-report

These extend ARCHITECTURE §11:

- **Logging is not random.** People log more on bad days. Prompted capture
  (the evening review) is less biased than ad-hoc capture, so weight review
  ratings above moment tags when the two disagree.
- **Reactivity.** Tracking anxiety can change anxiety. Expect the first few
  weeks to look different; don't read early trends as real.
- **Small n.** At one tag per few days, a tag needs about two months before
  any effect is credible. Show support (`n_tagged`) next to every effect.
- **Vocabulary sprawl kills statistics.** Twenty tags with 3 uses each give
  nothing; five tags with 30 uses each give answers. Keep the vocabulary
  small and merge aliases aggressively.
- **Confounding by context.** Vacation changes sleep, steps, alcohol and mood
  all at once. Spans must be modelled, not ignored.
- **Correlation ≠ causation**, especially here: "coffee → anxiety" and "anxiety →
  coffee" look the same at lag 0. The lag ±1 asymmetry is a hint, not proof.

---

## 8. Privacy

Journal text is the most sensitive data in the system, more than heart rate.

- It stays on the box: no cloud, and only the local LLM for normalisation.
- Tailscale-only access by default; no public exposure of `/api/journal` unless
  the Watch path forces it, and then with a scoped secret.
- The narration gets tag statistics, not note text (§6.5).
- It's covered by the existing nightly `backup.sh` (it's in the same
  database), but that also means the backup disk holds journal text. Treat
  the backup location accordingly, especially if an off-site copy is
  added later (encrypt it).

---

## 9. Build order

| Phase | What | Effort | Value |
|---|---|---|---|
| **0, now** | Start logging State of Mind on the Watch/phone (moods, labels, associations). Optional stopgap Shortcut posting `tag_*` metrics to `/api/ingest` (§3c). | none | data starts accumulating; the analysis needs ~2 months of it anyway |
| **1** | Parse `stateOfMind` → `state_of_mind` table; `rederive` it from `raw_ingest`; `mood_valence_*` daily series into the correlation pass; Grafana annotations | small | first real mood correlations, backfilled from history |
| **2** | `journal_entries` + `tag_vocabulary` + `/api/journal` (scoped secret or Tailscale identity), deterministic normalisation, the Siri Shortcut | medium | custom tags from voice |
| **3** | The PWA daily review + `day_reviews`; edit/delete with tombstones | medium | unbiased zeros (§6.1), ratings, habits, context spans |
| **4** | `tag_effect` + `tag_intraday` findings; narration section | medium | "what affects me" answers |
| **5** | LLM-assisted normalisation of unmatched text; tag merge/curation UI | small | less friction, cleaner vocabulary |

Phases 0 and 1 are worth doing even if nothing else gets built: Phase 0 costs
nothing, and Phase 1 turns data you're already sending into findings.

## 10. Open questions

1. **Tailscale:** is the server already on a tailnet, and how does HAE reach
   it today (tailnet, public reverse proxy, LAN)? That decides the auth model
   in §5.
2. **Watch reachability:** does a Watch-run Shortcut go through the iPhone's
   Tailscale? Test with a trivial `GET` before designing around it.
3. **Starter vocabulary:** which 5–10 tags matter most? (Suggested: anxiety,
   caffeine, alcohol, family-conflict, social-time, outdoors, headache,
   late-meal, plus spans vacation/sick/travel.)
4. **Intensity scale:** 1–3 (simple to say) or 1–5 (matches the ratings)?
5. **Upstream or local?** Phase 1 (State of Mind) is generic and a good
   upstream PR; the journal and PWA might stay a local feature, or be
   proposed upstream as an optional module. ARCHITECTURE §10 lists "a
   dedicated web app" as out of scope, so it's worth asking the maintainer
   first.
