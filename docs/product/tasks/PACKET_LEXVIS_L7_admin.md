# PACKET LEXVIS L7 — /admin engagement console + bot screening

Workdir: `/home/pranav/lexvisibility`. **Read first:**
`/home/pranav/AIAudit/app/bot_filter.py` (port this — it is the house
pattern), `/home/pranav/AIAudit/app/main.py` (the /admin + /admin.json
routes + display filters, for UX reference), then this repo's `app/main.py`
(report/event intake), `frontend/` conventions.

You are Codex. No commit/push/restarts/LLM calls; no live HTTP in tests.

## Why

13 tracked emails go out this morning (each report link carries ?ref=<code>).
The operator needs one page answering: who clicked, when, and what did they
do on the report — with curl/scanners/email-prefetch bots screened out so a
SafeLinks prefetch doesn't masquerade as the founder reading the report (or
worse, fire the call-now relay upstream).

## Scope

### 1. Bot screening (backend)

- Port AIAudit's `bot_filter.py` (UA substring rules incl. curl/wget/python/
  go-http, scanner names, email link-protection prefetchers; `classify(ua,
  ip) -> (is_bot, reason)`) into `app/bot_filter.py`, adapted freely.
- `report_events` gains columns (checkfirst ALTER): `user_agent TEXT`,
  `client_ip TEXT`, `is_bot INTEGER`, `bot_reason TEXT`.
- Every recording path (report GET view log, beacon intake, PDF download)
  captures UA + client IP (honor `X-Forwarded-For` first value / `X-Real-IP`
  — nginx fronts this app) and stores the classification.
- **Relay suppression:** the EmailTag relay (report_viewed/report_engaged)
  must NOT fire from bot-classified events. Human-classified only.
- Legacy rows (no UA): leave is_bot NULL = "unknown"; admin treats unknown
  as excluded-by-default. Refs beginning `test-` are test traffic — flagged
  and excluded by default in the admin regardless of UA.

### 2. Ref labels

- `runs` gains `ref_labels_json TEXT` (checkfirst ALTER): map of ref code →
  display label ("rb" → "Ryan G. Block — Managing Partner").
- CLI: `bin/lexvis run set-ref-labels <run_id> '<json>'` (and show in
  `run show`).

### 3. Admin API

`GET /api/admin/engagement?run_id=<id>&include_bots=0&include_tests=0`
(NO auth — operator decision; read-only endpoint):
- summary: totals (human views, bot hits screened, pdf downloads, refs seen);
- per-ref rows: label, ref, first_seen, last_seen, view count, max scroll,
  sections seen (of 5), verify_copied / appendix / booking / pdf booleans,
  approx seconds, and a `journey`: chronological plain-English steps built
  from events ("opened the report", "reached page 3 of 5", "scrolled 75%",
  "copied the verify query", "downloaded the PDF", "clicked booking");
- unattributed bucket (no ref) kept separate;
- bots bucket: count by bot_reason (visible when include_bots=1).
- `GET /api/admin/runs` — id, firm, status, report token, event counts.

### 4. Admin UI

`/admin` (Next.js route, NO auth):
- run picker (default: most recent done run);
- headline cards: human opens, unique refs seen, PDFs, bots screened;
- the recipient table (per-ref rows above), sorted by last activity,
  hot signals highlighted (verify/booking/pdf = badge);
- click a row → expandable journey timeline with human-readable timestamps
  in America/Los_Angeles;
- toggles: include bots, include test refs, auto-refresh every 30s (polling);
- keep it dense and readable — this is an ops screen, not a marketing page.
- Print/PDF styling not needed. Do NOT link /admin from any public page.

### 5. Tests

- curl/wget/python UAs and empty UA → is_bot with reason; normal desktop
  and mobile browser UAs → human.
- Beacon + view + pdf paths store UA/IP/classification.
- Relay poster NOT called for bot events; called for human ones.
- Admin API: per-ref rollup + journey ordering; bots/tests excluded by
  default, included with flags; ref labels applied.
- Existing suite green; `npm run build` + lint clean.

## Guardrails

- Additive only; no changes to page rendering or QA gate; no nginx edits.
- Do NOT `git commit`/`git push`.

## Report

Files changed, bot rule list, admin routes, test list, STOP.
