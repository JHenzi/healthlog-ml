# Risks, mitigations and test suites

Every known way this project can go wrong, what we do about it, and the
test that proves the mitigation works. The **rules** that follow from it are
binding and live in [`../CLAUDE.md`](../CLAUDE.md); each risk below names the
rule it backs (R-numbers).

Status legend: **LIVE** = affects the running system today, *design* = must
be handled when the relevant milestone is built.

---

## 0. Live findings (found while writing this, 2026-10-15)

| ID | Finding | Impact | Action |
|---|---|---|---|
| L1 | **HealthLog runs with `TZ=Europe/Vienna`**: `.env` has no `TZ`, so compose's default applies; the user is in US Eastern | Every HealthLog daily value is bucketed on Vienna days: **a "day" runs ~18:00–18:00 Eastern**. Daily sums, sleep dates, stress/energy days, anomalies and correlations are all shifted. Raw timestamps are correct (`timestamptz`). | Set `TZ=America/New_York` in `.env`, recreate the container, then recompute: `healthlog analyze`, `healthlog rederive-stress`, `healthlog rederive-body-battery`. Our own engine never inherits this: R14. |
| L1b | **Upstream hard-codes Vienna** beyond `TZ`: the `daily_metrics` view (migrations 0001/0005: `AT TIME ZONE 'Europe/Vienna'`) and the Grafana dashboards (`"timezone": "Europe/Vienna"` plus a hidden `$tz` constant in `overview.json`) | Even with `TZ` set, the view and Grafana keep Vienna days, so **Grafana and the analysis disagree** about what a day is. Affects every non-Vienna user. | **Upstream PR** (track A): the view reads the zone from a database setting written at migrate/startup from `TZ`; dashboards follow the same setting (or the browser); a `healthlog audit` warning when `TZ` doesn't match the UTC offsets in incoming payloads; `TZ` uncommented in `.env.example`. Our engine is unaffected: it reads base tables, never upstream's views (R3). |
| L2 | `heart_rate` arrives from **three overlapping sources** (Watch, iPhone, HAE's merged stream) | Averages mildly biased; any count/sum across sources double-counts. `step_count` and `active_energy` currently arrive merged only (one source), but that depends on HAE settings. | Per-metric source policy in our loader (R16); test D2. |

---

## A. Coupling with upstream

| ID | Risk | Impact | Mitigation | Tests |
|---|---|---|---|---|
| A1 | Our DB objects depend on upstream objects, so their `DROP VIEW/TABLE` fails (they do this in 0016, 0020, 0021) | **Upstream upgrade breaks on our machine** | No views, FKs or SQL-body functions referencing `public`; reads happen in application queries only (R2) | `test_no_dependencies_on_public`: queries `pg_depend` / `pg_rewrite` / `pg_constraint` for any `companion` object referencing a `public` object; must be empty |
| A2 | Upstream renames/removes a table or column we read | features break silently | All upstream reads through `app/upstream.py` (R3); `check-upstream` at startup and before every job | `test_contract_matches_schema`; **upstream-compat CI job**: run upstream's migrations from `upstream/dev` on an empty DB, then our contract check (early warning before their release) |
| A3 | Upstream code reads leak outside the contract module | contract check gives false confidence | static rule (R3) | `test_upstream_reads_only_in_contract`: grep the package for upstream table names outside `app/upstream.py` |
| A4 | New upstream tables aren't readable by our role | contract check fails after an upgrade | bootstrap grants `ALTER DEFAULT PRIVILEGES FOR ROLE healthlog IN SCHEMA public GRANT SELECT ON TABLES TO companion` | integration: create a table as `healthlog`, assert `companion` can `SELECT` it |
| A5 | Our role can write upstream data (bug or bad grant) | data corruption | `SELECT`-only grants on `public` (R2) | `test_role_cannot_write_public`: INSERT/UPDATE/DELETE/TRUNCATE/CREATE in `public` as `companion` must all fail |
| A6 | We edit upstream-owned files in the fork | merge conflicts on every sync | path allowlist (R1) | CI `check-paths`: `git diff upstream/main...HEAD --name-only` must only touch allowlisted paths on companion branches |
| A7 | Our jobs read while upstream is migrating or mid-analysis | transient errors or half-written findings | run after upstream's analysis completes: check `/config/state/last_analysis` timestamp, retry with backoff; never read `findings` mid-run | unit: job waits/retries when the marker is stale; integration: job tolerates a missing table gracefully |
| A8 | Upstream or the pinned DB image drops `pgvector`, or changes Timescale/Postgres versions | diary features break; restore incompatibility | startup check for the extension; `float4[]` fallback; restore drill after any DB image change | `test_extension_present` (warn → feature off, not crash) |
| A9 | Restore from backup loses our schema, role or extension | data loss on recovery | `backup.sh` dumps the whole DB + roles; scripted restore drill | `restore-drill` script: restore into a throwaway container, compare row counts for **both** schemas, run `check-upstream` |

## B. Data correctness

| ID | Risk | Impact | Mitigation | Tests |
|---|---|---|---|---|
| B1 | Wrong time zone / day boundary (see L1) | every daily feature shifted | explicit `TZ` and `DAY_BOUNDARY` settings; timezone-aware datetimes only (R14); ruff `DTZ` rules | fixtures at 03:59 vs 04:00; a sleep crossing midnight; config without `TZ` must refuse to start |
| B2 | **DST transitions** (23 h / 25 h days; 2026-03-08 and 2026-11-01 in the US) | duplicated or missing hour, wrong daily sums | compute days in local time from aware timestamps; never add 24 h to get "tomorrow" | DST fixtures: daily sums correct on both transition days; hourly features have 23/25 rows |
| B3 | Travel across time zones | events land on the wrong day | store UTC + the offset the device reported; day = local day at the event's own offset | fixture: entries logged in another time zone fall on the right local day |
| B4 | Missing treated as zero | effects diluted toward nothing | the reviewed-day rule (R7) | unit: untagged + reviewed day → 0; untagged + unreviewed → NaN |
| B5 | Late-arriving data (HAE syncs late) | insights computed on incomplete days | recompute a trailing window (e.g. 7 days) each run; mark days "complete" only after the next day's sync | unit: a late sample for day *t−2* changes that day's features on the next run |
| B6 | Unit drift (e.g. energy arrives in kJ; upstream converts to kcal) | wrong magnitudes | read canonical units from upstream's registry; refuse metrics whose unit we don't know | unit: a kJ fixture is converted; an unknown unit is rejected, not passed through |
| B7 | Duplicate capture (Shortcut retry, double tap) | inflated counts | `client_id` idempotency; optional per-tracker double-tap window | API: same `client_id` twice → one row; two taps within the window → one row (if enabled) |
| B8 | Bad device clocks / future timestamps | entries on wrong days | reject `time > now + 5 min`; accept back-dating | API validation tests |
| B9 | Changing a tracker's type or scale corrupts history | old values reinterpreted | type/unit/scale locked once data exists; versioning (R12) | API: changing a locked field → 409; successor link created |
| B10 | Derived tables drift from the event log | edits or deletes "come back" | event log is the source of truth; full rebuild command | property test: random sequences of create/edit/delete → `rebuild()` equals incremental state |
| B11 | Offline edits on two devices conflict | lost edits | last-write-wins on `updated_at`, with the loser kept in the event log | unit: two conflicting edits resolve deterministically |
| B12 | Source overlap (see L2) | double counting | per-metric source policy: prefer the merged stream, else a priority list (R16) | fixture with Watch + iPhone overlap: sums not doubled, averages unbiased |

## C. Statistical and ML validity

| ID | Risk | Impact | Mitigation | Tests |
|---|---|---|---|---|
| C1 | False discoveries from many features × lags × horizons | confident nonsense | FDR across the full family; one distributed lag model = one test; minimum support; effect floors (R8) | **null-calibration suite**: 200 seeded pure-noise datasets → reported false-discovery proportion ≤ target |
| C2 | Missed real effects (power) | engine looks useless | planted-effect validation | **planted-effect suite**: same-day, lag-2, curved and spread-out effects of known size are found at the expected rate |
| C3 | Confounding (weekday, season, rainy *weeks*, vacation) | spurious links | residualise weekday + trend; spans excluded; distributed lag models control other lags; adjusted re-check of top insights | planted **confounded** effect (X and Y both driven by Z) must be rejected or annotated "explained by Z" |
| C4 | Autocorrelation inflating significance | too many "significant" results | residuals; block bootstrap where needed | null suite includes autocorrelated noise (AR(1)), not just white noise |
| C5 | ML leakage (random CV, future features) | inflated accuracy, wrong drivers | time-ordered CV only; feature builder asserts feature time < target time (R9) | `test_no_future_features`; CV splitter test: every test fold is strictly after its train fold |
| C6 | Overfitting on small n | spurious "drivers" | regularised/simple models; must beat a naive baseline; minimum history (R9) | a model on noise must not beat the baseline → nothing reported |
| C7 | Unstable insights (flip run to run) | user distrust | require persistence across runs, or bootstrap stability ≥ threshold | stability test: resampling the data keeps top insights stable on planted data |
| C8 | Causal or diagnostic wording | misleading, medically risky | association-only templates (R10) | **wording lint**: templates must not contain *cause(s), because, leads to, diagnos*, …; every sentence includes *n* (R13) |
| C9 | Self-report bias (logging more on bad days) | biased effects | prompted review, reviewed-day rule, logging-coverage indicator shown next to insights | unit: coverage metric computed; insights below a coverage floor are flagged |

## D. Security

| ID | Risk | Impact | Mitigation | Tests |
|---|---|---|---|---|
| D1 | Password brute force | account takeover | argon2 hashes; rate limit + lockout; HTTPS required | auth: N failed logins → lockout; the hash is never logged |
| D2 | CSRF on cookie-authenticated forms | forged writes | `SameSite=Strict` + CSRF token on every state-changing form | a POST without/with a wrong token → 403 |
| D3 | XSS via user text (tracker names, diary, notes) | session theft | Jinja autoescape; strict CSP; no `innerHTML` with user data | render `<script>`/attribute payloads → escaped; CSP header present |
| D4 | Token leakage or over-broad tokens | unauthorised access | scoped tokens (`all`/`read`/`log:<key>`), hashed at rest, revocable, never logged (R11) | **scope matrix**: every token scope × every endpoint → expected allow/deny; logs scanned for token strings |
| D5 | Injection via tracker keys or feature names in dynamic SQL | DB compromise | keys validated against `^[a-z][a-z0-9_]{0,63}$`; parameterised queries only | fuzz keys with SQL metacharacters → rejected |
| D6 | Trusted-proxy header spoofing (`proxy_header` mode) | auth bypass | honour identity headers **only** from `TRUSTED_PROXIES` | a request with the header from an untrusted IP → 401 |
| D7 | Vulnerable dependencies | exploitation | pinned requirements; Dependabot (as upstream); `pip-audit` in CI | CI job |

## E. Privacy

| ID | Risk | Impact | Mitigation | Tests |
|---|---|---|---|---|
| E1 | Personal data committed to the **public** fork | permanent public leak | synthetic fixtures only; no exports/dumps in git (R4) | CI **repo scan**: forbid `HealthAutoExport*`, `*.dump`, JSON > 1 MB, and real HAE-style UUIDs in fixtures; `gitleaks` for secrets |
| E2 | Hidden external calls (e.g. model weights downloaded at runtime) | data/metadata leaves the box; breaks offline | models baked into the image at build time; `HF_HUB_OFFLINE=1`; network egress only to allowlisted, opt-in sources (R5) | **egress test**: run the app and nightly job with networking disabled → everything except opt-in fetchers works; the HTTP client rejects non-allowlisted hosts |
| E3 | Outside-data requests reveal too much | location tracking | coarse fixed location (~10 km), date ranges only, batched daily | unit: the request builder rounds coordinates and sends no other parameters |
| E4 | Diary text reaches an LLM prompt or logs | sensitive text exposure | diary excluded from narration unless opted in; never logged | unit: narration context builder contains no diary text by default; log capture contains no entry text |
| E5 | "Deleted" diary text survives in the event log and backups | can't truly delete | **purge** operation: redact payloads in the event log and every derived table; backups age out by retention (14 days) | purge test: after purge, the text appears nowhere in the DB (`pg_dump` grep) |
| E6 | Backup disk holds secrets + diary in clear | exposure if the disk leaves the house | `0600`/`0700` perms (done); encrypt any off-site copy (restic) | `backup.sh` check: output dir mode 700 |

## F. Operations

| ID | Risk | Impact | Mitigation | Tests |
|---|---|---|---|---|
| F1 | Nightly jobs exhaust RAM/CPU on the shared server (the backfill needed GBs) | DB or upstream starves | `mem_limit`/`cpus` on `companion-jobs`; chunked loading; time budget per job | perf test: 2 years of synthetic minute data → job under N minutes and M GB |
| F2 | Our migrations fail on a populated DB | downtime | migrations tested up **and** down, on empty and populated DBs | migration suite: `upgrade head` → `downgrade base` → `upgrade head` with fixture data |
| F3 | Job ordering vs upstream (03:30) and backups (04:30) | stale reads, contention | 04:15 after upstream's completion marker (A7); `pg_dump` is snapshot-consistent anyway | — |
| F4 | iOS updates break the Shortcut | capture silently fails | the Shortcut reports "Not saved" on failure; manual checklist after each iOS release | manual test checklist (docs) |
| F5 | Silent job failures | stale insights | job outcome notifications (reuse Gotify/PushBits like upstream); "last run" shown in the UI | unit: a failed job emits a notification and marks the run failed |

## G. Product and scope

| ID | Risk | Mitigation |
|---|---|---|
| G1 | Logging fatigue → sparse data | Apple Health for what it models; one-tap Shortcut; review ≤ 60 s; coverage indicator |
| G2 | Insight overload or noise | ranking, minimum support, "not enough data yet" states |
| G3 | Medical overreach | association wording (R10); "discuss with a clinician" where health-relevant; no diagnoses |
| G4 | Scope creep | milestones ship usable slices; M6+ only when the data asks (plan.md) |

---

## Test suite layout

```
companion/tests/
├── unit/           pure functions: type system, features, time/DST, wording lint      (every commit)
├── integration/    real TimescaleDB: API, auth, migrations, event-log rebuild          (every commit)
├── contract/       upstream coupling: no-dependency, role permissions, read contract   (every commit)
├── security/       auth, CSRF, XSS, token scope matrix, injection, proxy spoofing      (every commit)
├── privacy/        egress block, log scrubbing, purge, repo scan                        (every commit)
├── stats/          planted-effect, null-calibration, confounding, stability, leakage   (nightly; seeded, slow)
└── e2e/            compose smoke: boot, login, log via API, nightly job, Today page     (before merge to main)
```

**CI in the fork:**
- every push: lint + unit + integration + contract + security + privacy;
- nightly: stats suite, plus the **upstream-compat** job (upstream `dev` migrations + our contract check);
- before merging a milestone: e2e + the restore drill.

**Definition of done for any analysis method:** it finds planted effects at
the expected rate, stays within its false-discovery target on null data,
rejects planted confounders, and its sentences pass the wording lint.
