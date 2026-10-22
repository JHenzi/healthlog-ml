# Companion API

Every JSON route the Companion serves, for Shortcuts, NFC tags, scripts and
anything else that can send an HTTP request. **Rule R18:** a route under
`/api` is added, changed or removed together with its entry here, and
`tests/contract/test_api_docs.py` fails if one is missing.

The web pages' own forms (`/log/…`, `/review`, `/trackers/…`) are not an API:
they need a browser session and a CSRF token. Use the routes below instead.

## Basics

- **Base URL:** your Companion over HTTPS, e.g. `https://<host>.<tailnet>.ts.net:8443`.
  Plain HTTP isn't supported (see the README, *HTTPS*).
- **Auth:** `Authorization: Bearer hlc_…` on every route except `/api/health`.
- **Body:** JSON, with `Content-Type: application/json`.
- **Days** follow the Companion's day boundary (`DAY_BOUNDARY`, default
  04:00): an entry at 01:30 belongs to the evening before.
- **Times** are ISO 8601 with an offset (`2026-10-21T21:30:00-04:00`).
- **Retries are safe** when you send a `client_id` (any UUID): the same id
  twice logs once.

## Tokens and scopes

A token has one scope:

| Scope | Allows |
|---|---|
| `read` | every `GET` route |
| `log:<tracker_key>` | `POST /api/log/<tracker_key>` for that one tracker, nothing else |
| `all` | everything, including deleting entries |

Create them on a tracker's **Set up** panel (`log:<key>` tokens) or with the
CLI. A token is shown once and stored hashed.

```bash
docker exec healthlog-companion companion token create "iPhone" --scope all
docker exec healthlog-companion companion token list
docker exec healthlog-companion companion token revoke 3
```

## Errors

Errors come back as `{"detail": "<message>"}`. A Shortcut can show `detail`
as is.

| Status | Means |
|---|---|
| 401 | no token, or it's wrong or revoked |
| 403 | the token's scope doesn't allow this |
| 404 | no such tracker or entry |
| 422 | the value doesn't fit the tracker (e.g. a rating of 11), a time more than 5 minutes ahead, or a malformed body |

## Routes

### `GET /api/health`

No token. Whether the Companion and its database answer.

```json
{"status": "ok"}
```

### `GET /api/today`

Scope `read`. The Overview's sentences for today, plus notes (streaks,
records) and data problems.

```json
{"day": "2026-10-21", "sentences": ["…"], "notes": ["…"], "problems": []}
```

### `GET /api/insights`

Scope `read`. Every reported finding, strongest first.

```json
{"insights": [{"id": 12, "kind": "association", "horizon": "day", "sentence": "…",
  "feature_a": "sleep.total_h", "feature_b": "hl.step_count", "lag": 1, "method": "spearman",
  "effect": 0.42, "p_adj": 0.01, "n": 61, "strength": "moderate", "computed_at": "2026-10-21T08:15:02+00:00"}]}
```

### `GET /api/trackers`

Scope `read`. The trackers that aren't archived, for a Shortcut's *Choose
from List*. `scale` is `[min, max]` for ratings, `options` the choices for a
pick-one.

```json
{"trackers": [{"key": "coffee", "name": "Coffee", "type": "count", "unit": "cups",
  "scale": null, "options": null, "pinned": true}]}
```

### `POST /api/log/<tracker_key>`

Scope `log:<tracker_key>` or `all`. Log one entry.

```json
{"value": 2, "time": "2026-10-21T07:10:00-04:00", "client_id": "5f1c…", "source": "shortcut"}
```

Every field is optional:

- `value` depends on the tracker's type:

  | Type | `value` |
  |---|---|
  | count | a whole number (default 1) |
  | yes/no | `yes`/`no`, `true`/`false` or `1`/`0` (default yes) |
  | rating | a number on its scale (1–10) |
  | amount, minutes | a number, 0 or more |
  | pick-one | one of its options |
  | moment | an intensity from 1 to 3 (optional) |
  | time of day | none: the entry's time is the value |
- `time` back-dates the entry. It defaults to now.
- `client_id` makes a retry safe.
- `source` labels where the entry came from (at most 32 characters, default `api`).

Reply: `201` when it's new, `200` when the `client_id` was already logged.
`message` is meant to be spoken back, so a misheard entry is caught right
away.

```json
{"client_id": "5f1c…", "tracker": "coffee", "value": 2.0, "time": "2026-10-21T11:10:00+00:00",
 "day": "2026-10-21", "created": true, "message": "Logged Coffee at 07:10"}
```

```bash
curl -X POST -H "Authorization: Bearer hlc_…" -H "Content-Type: application/json" \
  -d '{"value": 2}' https://<host>:8443/api/log/coffee
```

**The day rating** is built in and needs no setup:

- `POST /api/log/day_rating` with `{"value": 7}` logs tonight's "How was
  today?" (1–10).
- The next-morning look back (`day_rating_lookback`) is about the day before,
  so it's refused here (422). Log it on the Overview.

Day tags can't be logged through the API yet (next-steps §4.3).

### `DELETE /api/entries/<client_id>`

Scope `all`. Remove one entry. It stays in the event log as a tombstone.

```json
{"deleted": "5f1c…"}
```

## In a Shortcut

Use **Get Contents of URL**:
- **Method:** `POST`
- **Headers:** `Authorization` = `Bearer hlc_…`
- **Request Body:** JSON, with a `value` field.

Then **Get Dictionary Value** `message` (or `detail` on an error) and
**Speak Text** it.

For a generic "Track" Shortcut:
1. `GET /api/trackers` with a `read` token.
2. *Choose from List* on `name`.
3. Post to `/api/log/<key>` with an `all` token.
