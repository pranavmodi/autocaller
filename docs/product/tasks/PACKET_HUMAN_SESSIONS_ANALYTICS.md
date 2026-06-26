# PACKET B — Surface beacon "human sessions" in click-analytics

**Repo / workdir:** `/home/pranav/possibleos`. **You are Codex.** Backend +
frontend + tests. **Do NOT commit, push, restart services, or run migrations.**
**Do NOT touch `CLAUDE.md` or any `docs/product/tasks/PACKET_FIRMINTEL_*` file**
(unrelated parallel-session WIP).

## Why
`/api/aiaudit/click-analytics` + the `/click-analytics` frontend page currently show
only **redirect clicks** (`audit_link_clicks`), which are dominated by email-security
scanners. The JS beacon now records **`page_session`** rows in `lead_gen_observations`
(a real-browser-only signal) but they are not surfaced anywhere. Add a trustworthy
**human-session** count alongside the clicks.

## Data facts
- `LeadGenObservationRow` (`lead_gen_observations`): columns `id, batch_id,
  batch_item_id, contact_id, pif_id, event_type, raw_event_json (JSONB), created_at`.
- Beacon rows: `event_type = 'page_session'`. `raw_event_json` keys:
  `event` (e.g. "session_ready"), `page`, `session_id`, `time_on_page_ms`,
  `channel` ("page_beacon"), `link_code`, `pif_id`.
- Existing endpoint: `app/api/aiaudit.py` `GET /api/aiaudit/click-analytics`
  (`since_days`, `group_by`, `limit`). Returns `summary`, `groups`, `recent_clicks`.

## Scope
1. **Backend — `app/api/aiaudit.py`.** In the click-analytics handler, after the
   existing click rollup, query `lead_gen_observations` where
   `event_type='page_session'` and `created_at >= now() - since_days`. Add to the
   JSON response:
   - `summary.human_session_count` = total page_session rows in window.
   - `summary.distinct_human_sessions` = `count(distinct raw_event_json->>'session_id')`.
   - `summary.click_count` already exists; also add `summary.human_to_click_ratio`
     = distinct_human_sessions / click_count (0 if no clicks; round to 3).
   - `human_sessions_by_page`: list of `{page, sessions, distinct_sessions,
     median_time_on_page_ms}` grouped by `raw_event_json->>'page'`, ordered desc,
     capped at `limit`. Use percentile_cont(0.5) for median over
     `(raw_event_json->>'time_on_page_ms')::int` (ignore nulls/zeros for the median).
   - `human_sessions_by_day`: `{day, distinct_sessions}` grouped by
     `to_char(created_at,'YYYY-MM-DD')`.
   Keep it read-only and defensive (page_session table may be empty -> zeros, no error).
2. **Frontend — `frontend/app/click-analytics/page.tsx` + the
   `ClickAnalyticsResponse` type in `frontend/lib/api.ts`.** Add the new fields to
   the type, and render near the top of the page a small summary block:
   **"Human sessions: <distinct_human_sessions>"** next to **"Clicks: <click_count>"**
   and the **human/click ratio**, plus a compact "Human sessions by page" table
   (page, sessions, median time on page). Keep styling consistent with the existing
   page. Make the new fields optional in the type so old responses don't break.

## Guardrails
- Touch only: `app/api/aiaudit.py`, `frontend/app/click-analytics/page.tsx`,
  `frontend/lib/api.ts`, and a test file. Nothing else. No migrations (the table
  exists). No service restart.

## Validation (paste output)
- `python3 -m py_compile app/api/aiaudit.py`.
- `cd frontend && npx tsc --noEmit` clean.
- A backend test (pytest, under `tests/`) that seeds 1 `audit_link_clicks` row and
  2 `page_session` observations (distinct session_ids) and asserts the analytics
  helper/endpoint returns `distinct_human_sessions == 2` and a correct ratio. If a
  DB fixture isn't readily available, instead unit-test the SQL-building/aggregation
  helper in isolation and say so.
- Note the exact JSON shape added so the orchestrator can curl-verify.

## Finish
Report diff + validation + the new JSON shape. Orchestrator reviews, restarts the
backend (after the active-call check), curl-verifies against live `page_session`
data, builds the frontend, commits, and pushes.
