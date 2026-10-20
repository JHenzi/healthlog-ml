# Privacy

What stays local, what leaves, and what is sent to models. Updated with each
milestone.

## As of M3 (weather, the almanac)

| Data | Where it lives | Leaves the server? |
|---|---|---|
| HealthLog's health data | HealthLog's schema `public`, read-only to us | no |
| Your password | argon2 hash in `companion.users` | no |
| Session cookies, API tokens | SHA-256 hashes only (`companion.sessions`, `companion.api_tokens`) | no |
| Today sentences | computed on request, not stored | only to your browser or token holder |
| State of Mind entries (valence, labels, associations) | copied into `companion.mood_entries` | no |
| Daily features (one number per day per series) | `companion.daily_features`, rebuilt nightly | no |
| Insights (sentences and their statistics) | `companion.insights`, replaced each run | only to your browser or token holder |
| Your trackers and every entry (values, times, device source) | `companion.trackers`, `events` (append-only), `observations` | no |
| Home location (if weather is on) | `.env` only (`WEATHER_LATITUDE`, `WEATHER_LONGITUDE`), given to the collector container | rounded to 0.1° (~10 km), to Open-Meteo |
| Hourly weather and air quality | the collector's file, then `companion.weather_hours` | no (it came from outside) |
| Latitude (if set) and holiday country | `.env`; the Companion uses the latitude, rounded to 0.1°, for day length | no: day length, moon and holidays are computed here |

- **No outbound network calls from the Companion.** It contains no HTTP
  client. `tests/privacy` checks that the app code imports none, and that the
  pages, login and contract check run with non-loopback connections blocked.
- **One opt-in exception: the weather collector** (`companion-collector`,
  off until you set a location). It is a separate container with no database
  credentials and no health data, on its own network (it can't reach the
  database). It sends Open-Meteo only a location rounded to 0.1° (~10 km), a
  date range and the variable names, once at backfill and then nightly, and
  connects to nothing but Open-Meteo's two hosts. It writes a CSV file that
  the Companion reads read-only and validates in full; a file with any bad
  line is ignored (`tests/unit/test_collector.py`, `test_outside.py`).
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
