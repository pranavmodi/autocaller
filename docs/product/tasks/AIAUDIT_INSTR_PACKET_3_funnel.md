# PACKET — AIAudit instrumentation 3/3: Layer 2 metrics + event funnel

Depends on packets 1+2 (audit_events populated). Workdir `/home/pranav/AIAudit`.
Touch only `app/db.py`, `app/main.py`, `bin/aiaudit`, `tests/`.

## Scope
Turn the event stream into the canonical human funnel + time/depth metrics.

1. **`funnel_stats(day=None)` in `app/db.py`** — extend (don't break the existing
   bot-filtered output) to also compute, from `audit_events` where `is_bot=0`:
   - funnel stages (distinct sessions reaching each):
     `real_session` (has session_ready) → `scrolled_to_q1` (scroll_depth>=25 or a
     question_view) → `first_answer` (any answer_selected) → `quick_read_done`
     (all quick-read question_ids answered) → `all_answered` → `submitted`
     (submit_success) → `email_captured`.
   - `median_ttfi_ms` (from first_interaction).
   - `pct_bounced_lt3s_no_scroll` — sessions with session_ready, no scroll_depth,
     no answer, and time_on_page < 3000ms (from abandon).
   - `pct_scrolled_no_answer` — scrolled to Q1 but no answer_selected.
   - device split where the session_ready payload carries viewport/screen.
2. **`/stats/funnel`** — surface the new fields.
3. **`bin/aiaudit funnel [--day]`** — print the event funnel (stage → count →
   %), median TTFI, and the two bounce percentages.

## Guardrails
No service restarts; temp port 18011 only if needed; delete TEST rows. Keep
backward-compatible output keys so nothing else that reads funnel_stats breaks.

## Validation (paste output)
- `python3 -m pytest tests/ -q` — all pass.
- `tests/test_funnel_events.py`: seed `audit_events` for 2-3 synthetic sessions
  (one bot, one bounce-<3s, one that answers Q1) and assert the funnel counts,
  median TTFI, and bounce percentages are correct.
- `bin/aiaudit funnel` runs and prints the new metrics.

## Finish
Report diff + validation. Do NOT commit or restart services.
