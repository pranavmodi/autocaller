# PACKET FIRMINTEL E4 — Outcome feedback + attribution (EmailTag)

Workdir: `/home/pranav/emailtag`. Source: `docs/FIRM_INTELLIGENCE_CONTRACT.md`
§6 (outcome feedback). **Depends on E0 (committed) and the Triggers packet
(`firm_event`)** — run **after** Triggers is committed (same files: v2 router,
models, migrations). This is the "measurement before shipping" layer: wire the
scoreboard so we learn which data points and triggers actually book.

You are Codex. Build + unit-test (mocked) only. Do NOT run against prod, do NOT
commit.

## Principle
possibleos reports GTM outcomes back; EmailTag (a) attributes each outcome to the
**signal/trigger and profile fields present at outreach time**, and (b) feeds
won/booked outcomes into `icp_scorer` as supervised signal. Outcomes sharpen the
neutral score; they must **never leak into the published facts** (no our-actions
in the facts layer).

## Scope (build all)

### 1. `firm_outcome` model + table (migration)
Fields: `id`, `firm_id` (FK, resolve via alias), `event`
(`contacted|replied|booked|qualified|won|lost|unsubscribed`), `occurred_at`,
`channel` (`email|call`), `detail` (JSONB), plus **attribution refs**:
- `firm_event_id` (nullable FK → the trigger that drove the outreach, if any)
- `attribution_snapshot` (JSONB): which core profile fields + which signal were
  present at outreach time (so "which signals convert" is answerable later).
Idempotent on a client-supplied `idempotency_key`.

### 2. `POST /api/v2/firm-intel/outcomes` endpoint
Auth `PIFSTATS_AUTH_TOKEN`. Accepts an outcome (+ optional `firm_event_id` and
snapshot), resolves the firm via the alias table, persists `firm_outcome`, and
marks the linked `firm_event.delivered_at`/converted if present.

### 3. Supervised-signal feed (no leakage)
- On `won`/`booked`/`qualified`, update `icp_scorer` inputs (e.g. a
  positive-outcomes signal the scorer reads) — adjust the **neutral score model
  inputs only**. Do NOT write outcome data into `firm_profile`'s published facts.

### 4. Attribution reporting (the scoreboard)
- `GET /api/v2/firm-intel/attribution` (read-only): aggregate booked/qualified
  rate by **trigger type** and by **core data-point present/absent** — i.e.
  "which signals and which of the 8–12 data points drive conversations."
- Keep it simple: counts + rates grouped by `firm_event.event_type` and by
  presence of each core field.

## Repo conventions
SQLAlchemy + Alembic (chain off the Triggers migration head); extend the v2
firm-intel router; pytest.

## Guardrails (hard)
- Build + unit-test (mocked auth/DB) only. No prod calls, no real outreach.
- Outcomes must **not** appear in the `firm_profile` serializer output (add a test
  asserting the facts layer is unchanged by outcomes).
- Additive; delete nothing. **Do NOT `git commit`/`git push`.**
- No service restarts, `/etc`, or Docker.

## Validation (run, report)
- `pytest test/ -k "outcome or attribution"` — all green.
- Test: `POST /outcomes` with a `booked` event + `firm_event_id` persists the
  outcome, links + marks the event, resolves firm via alias.
- Test: a `won` outcome updates the scorer input but the firm_profile facts are
  byte-identical (no leakage).
- Test: `GET /attribution` returns booked-rate grouped by trigger type and by
  data-point presence.

## Report (end of run)
Files added/changed + migration id, the attribution grouping it reports, how to
run tests, and STOP.
