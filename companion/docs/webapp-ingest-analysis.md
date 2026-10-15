# Ingest endpoint & webapp data-collection viability

An assessment of `POST /api/ingest` and whether a web app could be layered on
top of it to collect manually entered data (mood, caffeine, symptoms, …).

## The endpoint: `POST /api/ingest`

Defined in `backend/app/routers/ingest.py`; the pipeline lives in
`backend/app/ingest.py`.

- **Auth:** one shared secret in the `X-Ingest-Token` header, compared in
  constant time (`backend/app/deps.py`, `verify_ingest_token`). If
  `INGEST_SECRET` is unset, every request is rejected with 503 (fails closed).
  Failed attempts are audit-logged with the client IP, suitable for fail2ban.
- **Body:** capped at 32 MB by default (`MAX_PAYLOAD_BYTES`). The cap is
  enforced while the body streams in, not after it is fully buffered.
- **Pipeline** (`ingest_bytes`): parse JSON → SHA-256 the body → archive the
  raw payload verbatim in `raw_ingest`. If that hash is already archived, the
  request returns `duplicate`. Otherwise `parse_payload` turns the payload into
  rows and they are upserted.
- **Payload shape:** the Health Auto Export (HAE) format:
  `{"data": {"metrics": [{"name", "units", "data": [{"date", "qty" | Min/Avg/Max, "source"}]}], "workouts": [...]}}`.
- **Storage:** `metric_samples` upserts on `(metric, time, source)`. Unknown
  metrics are accepted and auto-registered as `secondary`, never rejected.
  Unit normalisation and plausibility bounds run first; values outside the
  bounds are dropped from the tables but kept in the raw archive.
- **After a store:** Prometheus counters update, an audit-log entry is written,
  and a best-effort notification push runs after the response is sent.

## Is a data-collection webapp viable?

Yes, with very little backend change, because ingest is metric-agnostic. A form
posting this would work today:

```json
{"data":{"metrics":[{"name":"mood","units":"score","data":[{"date":"2026-10-14 09:00:00 -0400","qty":7,"source":"webapp"}]}]}}
```

The data would be archived, deduplicated, stored in `metric_samples`, and
queryable in Grafana immediately. Points to resolve before building it:

1. **Auth is the real blocker.** The token is a single all-powerful secret
   designed for HAE. Embedded in browser JavaScript, anyone who loads the page
   can read it and write anything, including fake workouts. Options:
   - the webapp's own server-side route attaches the token, so the browser
     never sees it; or
   - a new router with its own auth: a separate secret, or a reverse-proxy
     login (Authelia, Authentik, Cloudflare Access) in front of the webapp's
     path only. HAE keeps using its header.
2. **Origin / CORS.** No CORS middleware is configured. Simplest is to serve
   the UI from the same FastAPI app (`StaticFiles`) or the same reverse-proxy
   host. `X-Frame-Options: DENY` is already set, which is fine.
3. **Editing works; deleting doesn't.** Re-posting the same
   `(metric, time, source)` overwrites the value, so corrections are free.
   There is no delete path, and every post is archived permanently in
   `raw_ingest`, so a re-derive would resurrect anything deleted straight from
   the tables. A delete feature needs a tombstone or an archive-aware design.
4. **Registry behaviour.** New metrics start as `secondary` with no bounds or
   unit rules. A metric's behaviour is its `metric_registry` row (data, not
   code); for the nightly analysis to treat manual metrics properly, add real
   registry rows (e.g. via a migration seed) rather than relying on
   auto-registration.
5. **Keep the raw-archive invariant.** Any new endpoint should build an
   HAE-shaped body and call `ingest_bytes`, not write tables directly. That
   preserves content-hash dedup, the verbatim archive, and re-derive for
   manual entries.

## Recommendation

- **No code:** an iOS Shortcut or a small server-side script that posts
  HAE-shaped JSON with the token. Works now; the secret never reaches a
  browser.
- **A real webapp:** add a small `routers/entries.py` with its own auth
  dependency and a typed Pydantic schema (metric, value, time, note). It
  converts input to the HAE shape and calls `ingest_bytes`, sharing the
  existing pipeline. Serve a static form from the same origin and add
  registry rows for the manual metrics. Roughly a few hundred lines. Docs
  impact: `README.md` for the new env var (second secret) and
  `docs/ARCHITECTURE.md` for the new ingestion path.

The hard part is the security model, not the data model; the database and
analysis side already accommodate extra metric sources.
