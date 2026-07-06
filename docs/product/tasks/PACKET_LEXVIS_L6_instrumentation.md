# PACKET LEXVIS L6 — report-page instrumentation + upstream engagement relay

Workdir: `/home/pranav/lexvisibility`. Read first: `app/main.py` (report API,
report_events from L4), `app/pipeline.py` (runs table, ensure-table pattern),
`frontend/components/PublicReportPage.tsx`, `frontend/lib/api.ts`.

You are Codex. No commit/push/restarts/LLM calls. No live HTTP in tests
(inject all posters/runners).

## Why

The Block LLP report is about to be emailed with per-recipient tracked links
(`?ref=<code>`). The page must tell the operator exactly what each recipient
did — first open, how far they read, whether they copied the verify query,
downloaded the PDF, clicked booking — and push view/engagement signals
upstream to EmailTag's firm-event stream. First-open data cannot be
retrofitted, so this ships BEFORE the send.

## Scope

### 1. Event intake (backend)

- Extend `report_events`: add columns `ref TEXT`, `session_id TEXT`,
  `meta_json TEXT` (checkfirst ALTERs, follow the existing ensure pattern).
  Extend allowed `event_type` set to: existing `report_viewed`,
  `pdf_downloaded`, plus `scroll_depth`, `section_seen`, `verify_copied`,
  `appendix_opened`, `booking_clicked`, `heartbeat`.
- `POST /api/report/{token}/events` (public, JSON
  `{event_type, ref?, session_id, meta?}`):
  - valid + QA-approved token only (404 unknown, 403 pending_qa);
  - event_type must be in the client-emitted set (scroll_depth,
    section_seen, verify_copied, appendix_opened, booking_clicked,
    heartbeat) — reject others 422;
  - `meta` size-capped (~1KB), per-session event cap (~500) to keep abuse
    boring; store row; 204 response.
- `GET /api/report/{token}` keeps logging `report_viewed`, now also storing
  `ref`/`session_id` when provided as query params (`?ref=&sid=`).
- Engagement rollup (`GET /api/runs/{id}/engagement` + `bin/lexvis
  engagement`) extended with per-ref summary: first/last seen, views,
  max scroll %, distinct sections seen, verify_copied / appendix_opened /
  booking_clicked / pdf_downloaded booleans, approx seconds on page
  (heartbeat count × interval).

### 2. Upstream relay (EmailTag firm-event stream)

- New `app/relay.py`: fire-and-forget poster to
  `{EMAILTAG_FIRM_INTEL_URL:-https://emailprocessing.mediflow360.com/api/v2/firm-intel}/events/external`,
  header `X-PIFStats-Auth-Token: $PIFSTATS_AUTH_TOKEN`, body per that API:
  `{vendor: "lexvisibility", signal_type, occurred_at, dedup_key, detail,
  domain: <run.firm_domain>}`.
- Runs table gains `firm_domain TEXT` (checkfirst ALTER; `run create
  --firm-domain` CLI option; editable via existing override path is NOT
  needed — a direct CLI `run set-domain <id> <domain>` subcommand is).
- Relay rules (server-side, on event intake):
  - first `report_viewed` per (run, ref) → signal `report_viewed`,
    dedup_key `lexvis:view:<run>:<ref>`;
  - first strong engagement per (run, ref) — any of verify_copied,
    booking_clicked, pdf_downloaded, or scroll_depth ≥ 75 — → signal
    `report_engaged`, dedup_key `lexvis:engaged:<run>:<ref>`.
  - Only when `firm_domain` set and token approved. Failures logged,
    swallowed (never break the page), retried at most once. Poster
    injectable for tests.

### 3. Frontend beacons

- Small `frontend/lib/beacon.ts`: `navigator.sendBeacon` with fetch-keepalive
  fallback; session_id = crypto.randomUUID persisted in sessionStorage;
  `ref` captured from `?ref=` query param and persisted in sessionStorage
  (so navigation to /appendix keeps it); all beacons carry both.
- On the report page: emit `section_seen` per page-block via
  IntersectionObserver (once per section per session); `scroll_depth` at
  25/50/75/100 milestones (once each); `verify_copied` on the copy button;
  `booking_clicked` on both booking buttons (do not prevent navigation);
  `heartbeat` every 15s while tab visible, max 40 per session;
  appendix page emits `appendix_opened` on load.
- The initial data fetch passes `?ref=&sid=` through to
  `GET /api/report/{token}` so the server-side view row is attributed.

### 4. Docs/CLI

README section: event vocabulary, ref-code convention, relay env vars.
`bin/lexvis engagement <run>` shows the per-ref table.

## Guardrails

- No cookies, no fingerprinting, no third-party analytics — first-party
  beacons only, and nothing beyond ref/session/meta above is stored.
- Existing tests stay green; report page must work with beacons blocked
  (all beacon calls wrapped, non-fatal).
- Do NOT `git commit`/`git push`.

## Validation (run, report)

- `pytest tests/ -q`: intake 403/404/422 paths; rows recorded with ref/sid;
  session cap enforced; rollup math incl. seconds-on-page; relay poster
  called exactly once per (run,ref) for view and once for engaged across
  multiple triggering events (injected poster records calls); no relay when
  firm_domain unset.
- `npm run build` + `npm run lint` clean.

## Report

Files changed, event vocabulary table, relay dedup scheme, test list, STOP.
