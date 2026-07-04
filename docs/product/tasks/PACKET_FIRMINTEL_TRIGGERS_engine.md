# PACKET FIRMINTEL TRIGGERS — Signal/trigger engine (EmailTag)

Workdir: `/home/pranav/emailtag`. Source: `docs/FIRM_INTELLIGENCE_CONTRACT.md`
§5 (events/moments). **Depends on E0 (committed).** Promotes the contract's
events layer from "phase 2" to a first-class **trigger engine** so signals
"reach us on their own" instead of us polling.

You are Codex. Build the engine + detectors + a **pluggable external-sensor
ingest**. Build + unit-test (mocked) only. Do NOT connect real third-party
services or run detectors against prod in this packet.

## Principle
The highest-value signals are **proprietary** — the live Precise email stream
EmailTag already receives. Build the trigger core on those; make external tools
(Common Room / Trigify / job boards) **optional pluggable sensors that feed in**,
never the system of record.

## Scope (build all)

### 1. `firm_event` model + table (migration)
Fields: `id`, `firm_id` (FK), `event_type`, `occurred_at`, `source`
(`precise_stream` | `engagement` | `external:<vendor>`), `detail` (JSONB),
`score` (priority), `dedup_key`, `delivered_at` (nullable), `created_at`.
Idempotent on `dedup_key` (never fire the same moment twice).

### 2. Internal detectors (the moat — run on Precise email/behavioral data)
Emit events from existing email/behavioral signals:
- `new_referral` (new referral in `inb_qfq9`), `records_surge` (spike in records inbox)
- `became_warm` (warm_score crosses threshold), `went_quiet` (no contact > N days
  after prior activity)
- `first_interaction` (first email from a new firm)
- `new_decision_maker` (new senior persona appears in signatures)
- `vendor_detected` / `vendor_changed` (case-mgmt domain drift)

### 3. Engagement detector
Emit `link_opened` / `link_clicked` events from aiscan/aiaudit tracking +
short-link hits (intent signal). (Ingest via the external endpoint below if the
tracking lives in possibleos.)

### 4. Pluggable external-sensor ingest
- `POST /api/v2/firm-intel/events/external` (auth: `PIFSTATS_AUTH_TOKEN`) that
  normalizes an inbound signal → `firm_event` (resolve firm via the alias table).
- A **sensor adapter interface** so Common Room / Trigify / a job-board scraper
  can be added as drivers WITHOUT changing the core. Ship ONE **stub** adapter +
  a documented contract; do **not** wire a real vendor in this packet.
- PI-relevant external signal types to accept: `job_posting` (intake/lien reqs),
  `pe_backed` / `new_office`, `news_mention`.

### 5. Delivery / exposure (pull now; push later)
- Expose recent events on the firm_profile and/or `GET /firms/{id}/events`
  (read-only). Mark `delivered_at` when consumed.
- The contract's push webhook (§5) is **phase 2** — leave a clean hook, don't build it.

### 6. Attribution hook
Each event carries an `id`; record it so downstream outcome feedback (E4) can
attribute "which trigger produced the booked conversation."

## Repo conventions
SQLAlchemy + Alembic; FastAPI router (extend the v2 firm-intel router); Celery
detector tasks; pytest.

## Guardrails (hard)
- Build + unit-test with fixtures/mocks. **Do NOT run detectors against prod**
  data and **do NOT connect real Common Room/Trigify** — stub adapter only.
- Additive; delete nothing. **Do NOT `git commit`/`git push`.**
- No service restarts, `/etc`, or Docker actions.

## Validation (run, report)
- `pytest test/ -k "event or trigger or sensor"` — all green.
- Test: a `went_quiet` fixture emits exactly one event; re-running does NOT
  duplicate it (dedup_key).
- Test: `POST /events/external` with a `job_posting` signal resolves the firm via
  alias and creates a `firm_event` (mocked auth).
- Test: `GET /firms/{id}/events` returns events read-only.

## Report (end of run)
Files added/changed + migration id, event-type catalog, the external-sensor
adapter contract, how to run tests, and STOP.
