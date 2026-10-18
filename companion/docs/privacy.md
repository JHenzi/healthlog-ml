# Privacy

What stays local, what leaves, and what is sent to models. Updated with each
milestone.

## As of M2

| Data | Where it lives | Leaves the server? |
|---|---|---|
| HealthLog's health data | HealthLog's schema `public`, read-only to us | no |
| Your password | argon2 hash in `companion.users` | no |
| Session cookies, API tokens | SHA-256 hashes only (`companion.sessions`, `companion.api_tokens`) | no |
| Today sentences | computed on request, not stored | only to your browser or token holder |
| State of Mind entries (valence, labels, associations) | copied into `companion.mood_entries` | no |
| Daily features (one number per day per series) | `companion.daily_features`, rebuilt nightly | no |

- **No outbound network calls.** The Companion contains no HTTP client.
  `tests/privacy` checks that the app code imports none, and that the pages,
  login and contract check run with non-loopback connections blocked. The
  first allowlisted, opt-in exception will be the weather fetcher (M3), which
  will send a rounded location (~10 km) and a date range, nothing else.
- **No telemetry**, no model downloads at runtime (`HF_HUB_OFFLINE=1` in the image).
- **Never logged:** the password (correct or not), session cookies, API tokens.
  A test captures the logs during login and API calls and checks for them.
- **No language model** sees anything yet. When narration arrives, diary text
  will be excluded unless you opt in (R11).
- **The repository is public.** Tests and docs use synthetic data only (R4). A
  privacy test fails on tracked Health Auto Export files, database dumps,
  `.env` files and JSON files over 1 MB.
- **Backups:** the nightly `backup.sh` dumps the whole database, so the
  `companion` schema and role are included.
