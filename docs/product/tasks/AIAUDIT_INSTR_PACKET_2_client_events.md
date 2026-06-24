# PACKET — AIAudit instrumentation 2/3: client event stream (Layer 1 full)

Depends on packet 1 (events table + `/api/audit/event` + `emitEvent` helper +
`session_id`). Workdir `/home/pranav/AIAudit`. Touch only
`app/templates/index.html` and `tests/`.

## Scope
Wire the full client event stream into the survey template using the
`emitEvent(type, extra)` helper from packet 1. Batch with `sendBeacon`; flush the
queue on `visibilitychange→hidden` and `pagehide`.

Emit:
- `first_interaction` — first answer/focus; payload `{ms_since_ready}` (TTFI).
- `scroll_depth` — fire once each at 25/50/75/100%.
- `question_view` — when a question enters the viewport (IntersectionObserver);
  payload `{question_id}`; record a per-question `viewed_at` for ms_since_view.
- `answer_selected` — on each radio change; `{question_id, value, ms_since_view}`.
- `step_next` / `step_back` — `{from, to}`.
- `provisional_score_shown` — when the header score first appears; `{stage}`.
- `submit_attempt`, `submit_success`.
- `gate_view`, `email_submitted`, `gate_abandoned` (gate.html if needed).
- `abandon` — on hide/pagehide: `{max_step, answered_count, time_on_page_ms, last_question_id}`.
- `js_error` — window 'error' handler; `{message}` (truncate).

Keep the existing `audit_progress` beacon. Keep payloads small.

## Guardrails
No service restarts; no backend changes (endpoint exists from packet 1); temp
port 18011 only if needed; delete any TEST rows.

## Validation (paste output)
- `python3 -m pytest tests/ -q` — all pass.
- Assert the rendered `/` page contains the wiring for each event type above
  (string checks on the template output, as `tests/test_app.py` does).
- Manual: note in the report that a real browser session would emit
  session_ready → question_view → answer_selected → … (no live browser needed).

## Finish
Report diff + validation. Do NOT commit or restart services.
