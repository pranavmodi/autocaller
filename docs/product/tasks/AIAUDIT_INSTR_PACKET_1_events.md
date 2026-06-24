# PACKET — AIAudit instrumentation 1/3: events foundation (Layer 0 + Layer 1 core)

Repo/workdir: `/home/pranav/AIAudit` (FastAPI + SQLite). Build on commit
`d91c2f7`/`1b156ba`. Full design: `/home/pranav/possibleos/long-response.md`
("Instrumentation design — AI Audit engagement diagnostics") and
`/home/pranav/AIAudit/docs/INSTRUMENTATION_BRIEF.md`.

## Scope (this packet ONLY)
Stand up the event pipeline + the human-denominator beacon. No client event
wiring beyond `session_ready` (that is packet 2); no funnel changes (packet 3).

1. **`audit_events` table** — add to `app/db.py` `_init_db_sync` (CREATE TABLE IF
   NOT EXISTS) plus an ALTER-safe migration mirroring the existing
   `_migrate_bot_columns` pattern:
   ```
   audit_events(id TEXT PRIMARY KEY, session_id TEXT, click_ref TEXT,
     ts TEXT NOT NULL, event_type TEXT NOT NULL, question_id TEXT, step INTEGER,
     payload_json TEXT, is_bot INTEGER NOT NULL DEFAULT 0, bot_reason TEXT)
   ```
   Indexes on `session_id`, `click_ref`, `ts`, `event_type`.
2. **`record_events(...)` in `app/db.py`** — insert one or many events; classify
   `is_bot`/`bot_reason` via `app.bot_filter.classify_client(ua, ip)`; tolerate
   missing optional fields.
3. **`POST /api/audit/event`** in `app/main.py` — accept a single event or a JSON
   array (sendBeacon posts `application/json`). Validate `event_type` against an
   allowlist constant (include at least: session_ready, first_interaction,
   scroll_depth, question_view, answer_selected, step_next, step_back,
   provisional_score_shown, submit_attempt, submit_success, gate_view,
   email_submitted, gate_abandoned, abandon, js_error). Capture ua/ip from the
   request. Return 204. Must be cheap + never raise to the client.
4. **Client (`app/templates/index.html`)** — on DOMContentLoaded: generate
   `session_id = crypto.randomUUID()`, keep it in a JS var + hidden input
   `session_id`, and `navigator.sendBeacon('/api/audit/event', ...)` a
   `session_ready` event with payload `{viewport, referrer, screen}`. Add a tiny
   `emitEvent(type, extra)` helper for packet 2 to reuse. Do NOT wire other
   events yet.

## Guardrails
- Touch only: `app/db.py`, `app/main.py`, `app/templates/index.html`, `tests/`.
- Keep all existing behavior + the existing `audit_progress` beacon working.
- No service restarts, no `/etc` writes, no `pip install` beyond
  `requirements.txt`. Temp test server on **port 18011** only if needed; tag any
  test rows and delete them before finishing.

## Validation (run these, paste output)
- `python3 -m pytest tests/ -q` — all pass.
- Add `tests/test_events.py`: POST a `session_ready` and a bot UA event to
  `/api/audit/event` (via httpx ASGITransport like `tests/test_app.py`), assert
  rows land in `audit_events` with correct `is_bot` (0 for a real browser UA, 1
  for `curl/8.3.0`).
- Assert the rendered `/` page contains the `session_id` generation + the
  `session_ready` sendBeacon call.

## Finish
Report the diff summary + validation output. Do NOT commit (orchestrator
commits). Do NOT restart `aiaudit.service`.
