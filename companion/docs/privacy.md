# Privacy

What stays local, what leaves, and what is sent to models. Updated with each
milestone.

## As of M3 (weather, the almanac)

| Data | Where it lives | Leaves the server? |
|---|---|---|
| HealthLog's health data | HealthLog's schema `public`, read-only to us | no |
| Your password | argon2 hash in `companion.users` | no |
| Session cookies, API tokens | SHA-256 hashes only (`companion.sessions`, `companion.api_tokens`) | no |
| Saved page copies (installed app, `web/static/sw.js`) | the phone's service-worker cache, only for a signed-in session; deleted on sign-out or when the session ends | no (never the API, sign-in or form posts) |
| Today sentences | computed on request, not stored | only to your browser or token holder |
| State of Mind entries (valence, labels, associations) | copied into `companion.mood_entries` | no |
| Daily features (one number per day per series) | `companion.daily_features`, rebuilt nightly | no |
| Insights (sentences and their statistics) | `companion.insights`, replaced each run | only to your browser or token holder |
| Your trackers and every entry (values, times, device source) | `companion.trackers`, `events` (append-only), `observations` | no |
| Home location (if weather is on) | `.env` only (`WEATHER_LATITUDE`, `WEATHER_LONGITUDE`), given to the collector container | rounded to 0.1° (~10 km), to Open-Meteo |
| Hourly weather and air quality | the collector's file, then `companion.weather_hours` | no (it came from outside) |
| Reminder subscriptions (if reminders are on) | `companion.push_subscriptions`: each device's push-service URL and its public encryption key | each reminder, encrypted for the device, to its push service (Apple's for an iPhone) |
| Latitude (if set) and holiday country | `.env`; the Companion uses the latitude, rounded to 0.1°, for day length | no: day length, moon and holidays are computed here |

- **No outbound network calls from the Companion.** It contains no HTTP
  client. `tests/privacy` checks that the app code imports none, and that the
  pages, login and contract check run with non-loopback connections blocked.
- **The network enforces it, in the Compose setup this project deploys.** The
  database, HealthLog and the Companion sit on an internal Docker network with
  no route out; small forwarders that hold no data publish their ports. Every
  deploy tries to connect out from each container and fails if one succeeds
  (`scripts/check_egress.sh`).
- **Grafana is the exception.** It can reach the internet, so plugins can be
  installed and data sources such as Hetzner Cloud work. Its analytics and
  update checks are off, and its database login is read-only, but a plugin you
  install can read what that login can read and could send it out.
- **One opt-in exception: the weather collector** (`companion-collector`,
  off until you set a location). It is a separate container with no database
  credentials and no health data, on its own network (it can't reach the
  database). It sends Open-Meteo only a location rounded to 0.1° (~10 km), a
  date range and the variable names, once at backfill and then nightly, and
  connects to nothing but Open-Meteo's two hosts. It writes a CSV file that
  the Companion reads read-only and validates in full; a file with any bad
  line is ignored (`tests/unit/test_collector.py`, `test_outside.py`).
- **A second opt-in exception: reminders** (`companion-courier`, idle until
  `PUSH_ENABLED=true` and the VAPID keys are set). The Companion seals each
  reminder for your phone (RFC 8291 encryption, a VAPID signature) and
  leaves it in a folder. The courier, built from the collector's image with
  the same isolation, posts it to the phone's push service and nothing else.
  The text is a fixed prompt ("How was today?"), never your values. Apple
  (or Google, Mozilla, Microsoft for other browsers) learns only that a
  message went to your device, and when. Only those services' hosts are
  accepted, on subscribing and in the courier; redirects aren't followed;
  messages older than 4 hours are dropped (`tests/unit/test_push.py`,
  risks.md E8).
- **No telemetry**, no model downloads at runtime (`HF_HUB_OFFLINE=1` in the image).
- **Never logged:** the password (correct or not), session cookies, API tokens.
- **A deleted entry stays in the event log** as a log event followed by a
  delete (a tombstone), so derived tables can be rebuilt. True erasure
  (`purge`) comes with the diary (M8), where it matters most.
  A test captures the logs during login and API calls and checks for them.
- **No language model** sees anything yet. When narration arrives, diary text
  will be excluded unless you opt in (R11).
- **The repository is public.** Tests and docs use synthetic data only (R4). A
  privacy test fails on tracked Health Auto Export files, database dumps,
  `.env` files and JSON files over 1 MB.
- **Backups:** the nightly `backup.sh` dumps the whole database, so the
  `companion` schema and role are included.

## Planned: comparing with others (M12, roadmap B13)

Nothing here is built, and **how summaries are exchanged is not decided**.
These are the rules any design has to meet:

- **Nothing leaves without your explicit action**, and the Companion makes
  no hidden calls (R5). Whatever channel is chosen gets its own privacy
  review first: once health data is published, it may not be recallable.
- **What a summary may hold:** coarse aggregates only:
  - medians over 30 or 90 days, banded (steps to the nearest 500, sleep to
    15 minutes), with extremes capped
  - learned good-day weights rounded to 0.05
  - the number of days of data
  - the kinds of links found, only between standard series (such as
    "sleep ↔ mood, same day, moderate")
  - optionally an age band, only if you add it
- **What a summary never holds:**
  - dates or time zone
  - location or weather
  - device or source names
  - ids of any kind (so two summaries can't be linked by an id)
  - free text, tracker names, tag names, mood labels or associations
    (names you chose can identify you)
- **You see every field before anything goes out.** Values unusual enough
  to narrow you down are marked, and any field can be dropped.
- **Reference figures** (published population averages) ship inside the
  image with their sources, so comparing with them needs no network.
- **Honest limits:** one person's summary can't be made anonymous in a strict
  (k-anonymity) sense; banding makes re-identification unlikely, not
  impossible. People who share are a self-selected group, so "others" is not
  "everyone".
