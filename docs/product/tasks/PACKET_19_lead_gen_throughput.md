# Packet 19 — /lead-gen P0: daily throughput funnel + evidence-supply unblock panel

## Goal
Turn the `/lead-gen` page from a scored list (which cannot tell the operator
whether 20 emails will actually send) into a **daily-throughput control panel**.
The operator's North Star: **≥20 high-quality emails out every day.** The page
must (1) show at a glance whether today's run will hit that, (2) name the
blocker, and (3) give the one action that fixes it.

Context: the system now auto-composes (angle-aware review-evidence variant),
auto-approves (`LEAD_GEN_AUTO_APPROVE_SEND=true`), and sends via the action
scheduler in the 9–11:30 PT window. The binding constraint is **review-evidence
supply among eligible firms** — this morning's run selected 20 but composed 0
(0 selected firms had usable reviews), so 0 will send. The page currently hides
this and even shows misleading copy.

## Read first
- `app/api/lead_gen.py` — existing lead-gen REST endpoints.
- `app/services/lead_gen_daily.py` — daily pipeline; `LeadGenDailyRunRow`,
  `_select_daily_contacts`, gate `held_reason="awaiting_review_evidence"`.
- `app/services/lead_gen_cybernetic.py` — `get_batch(batch_id)` (items carry
  `reason_json.agent_draft` and `reason_json.held_reason`).
- `app/services/review_extraction.py` — `firms_with_usable_evidence(pif_ids)`,
  `evidence_gate_kinds()`, `fetch_review_evidence`.
- `app/db/models.py` — `LeadGenDailyRunRow`, `LeadGenBatchItemRow`, `AgentActionRow`.
- `frontend/app/lead-gen/page.tsx` — the page (Tailwind; match its styles).
- `frontend/lib/api.ts` — API helpers + types (~line 1657 lead-gen block).
- `app/api/firm_reviews.py` — `PUT /api/firms/{pif_id}/reviews` (saving Yelp text
  already auto-extracts via REVIEW_AUTO_EXTRACT).

## Build

### 1. Backend: throughput endpoint
Add `GET /api/lead-gen/daily-run/throughput` (optional `?run_date=YYYY-MM-DD`,
default today PT). Returns JSON:
```json
{
  "run_date": "2026-06-18",
  "run_status": "completed",
  "batch_id": "…",
  "target": 20,                      // daily send budget
  "funnel": {
    "selected": 20,
    "with_evidence": 0,              // firms_with_usable_evidence over selected pif_ids
    "composed": 0,                   // items with reason_json.agent_draft
    "sending_today": 0,              // send_email actions: approved+scheduled today (PT) OR already succeeded today
    "sent_today": 0,                 // send_email actions succeeded today
    "held": 20                       // items with reason_json.held_reason
  },
  "verdict": { "will_hit_target": false, "shortfall": 20,
               "blocker": "no_review_evidence" },   // or "none" | "below_target"
  "held_firms": [
    { "pif_id": "…", "firm_name": "Anderson Law Firm, APC", "rank": 1,
      "warm_score": 514, "persona": "founder_owner",
      "contact_name": "Jonah Anderson", "contact_email": "jonah@…",
      "has_raw_reviews": false, "has_usable_evidence": false,
      "held_reason": "awaiting_review_evidence" }
  ]
}
```
Compute from today's `LeadGenDailyRunRow` + `get_batch`. `with_evidence` via
`firms_with_usable_evidence`. `sending_today`/`sent_today` from `AgentActionRow`
(action_type send_email, joined to the batch's items) by status + scheduled_for/
completed_at within today PT. `held_firms` sorted by score desc; `warm_score`
from item `reason_json` Front signal if present (else null); `has_raw_reviews`
from a `firm_reviews` row with non-empty raw yelp; `has_usable_evidence` from the
evidence set. Keep it read-only and resilient (missing run → zeros + run_status
"none").

### 2. CLI parity (golden rule)
Add `bin/possibleos lead-gen throughput [--date YYYY-MM-DD] [--json]` driving the
endpoint on loopback. Pretty-print the funnel + verdict + held count; `--json`
dumps raw. Add a row to the `docs/cli.md` §3 table.

### 3. Frontend: ThroughputPanel (hero, top of page)
Above everything else on `/lead-gen`. Horizontal funnel:
`Selected → With evidence → Composed → Sending today → Target`, each with its
number; highlight the first stage where the number collapses (e.g. With evidence
= 0) in red/amber. Below it a verdict line:
- green when `sending_today >= target`: "On track — N sending today."
- red when blocked: "⛔ M of {target} will send today. Blocker: no selected firm
  has usable reviews." (map `verdict.blocker`).
Include a small secondary line: "Yesterday: X sent · 7-day: Y / {7×target}".
Auto-send state chip: "Auto-send: ON" (read effective flag — expose via the
endpoint as `auto_send_on` boolean from `LEAD_GEN_AUTO_APPROVE_SEND`).

### 4. Frontend: UnblockPanel (shows when sending_today < target)
A prominent panel: "Unblock today — paste reviews for not-yet-covered firms."
Render `held_firms` as rows: rank · firm · warm · reviews badge (⛔ none / ◐ raw,
not extracted / ✅ evidence) · a **Paste reviews** control. Paste opens an inline
textarea; on save call `PUT /api/firms/{pif_id}/reviews` with `{yelp}` (this
auto-extracts). After save, show "extracting… / ✅ evidence found / no usable
quote yet" by re-fetching the throughput (or the firm's reviews). Add a **Re-run
now** button → `POST /api/lead-gen/daily-run {force:true}` then refetch. Show
"est. sends after re-run" = current with_evidence count.

### 5. Frontend: fix misleading copy
- Replace the banner at page.tsx ~L433: "Human approval stays in the loop … email
  sending still requires ALLOW_SEQUENCE_SEND=true" — this is FALSE now. New copy:
  "Autonomous send is ON: composed first-touch drafts auto-approve and send in
  the 9–11:30 PT window. Guards still apply: deterministic PHI patterns, send
  window, deliverability breaker." (Keep it factual; no em-dashes.)
- The "Agent slice / Create 3 approval-ready drafts / Selects 3 senior
  decision-maker contacts" block (~L245–260) is stale. Either remove it or move
  it under "Advanced" relabeled accurately (it creates approval-ready drafts for
  N contacts; sending now flows through auto-approve). Do not leave the "3
  senior decision-maker" / "no email is sent" wording.
- Where a run shows "20 drafts" but 0 are drafted, label using funnel data:
  "0 drafted · 20 held (awaiting reviews)".

## Constraints
- Additive: do NOT break existing approve/observe/preview/variant flows or the
  existing batch list. The new panels sit above the existing UI.
- Match the existing page's Tailwind styling + existing api.ts patterns; add
  typed helpers (`getLeadGenThroughput`) + TS types.
- No new heavy deps. No em-dashes in user-facing copy.
- Endpoint must be fast (one batch fetch + one evidence batch query); no per-firm
  LLM calls.

## Validation (include output)
- `python -c "import app.api.lead_gen"` clean.
- `curl -s localhost:8099/api/lead-gen/daily-run/throughput | python -m json.tool`
  shows today's real numbers (selected 20, with_evidence 0, composed 0,
  sending_today 0, held 20, verdict.will_hit_target false).
- `bin/possibleos lead-gen throughput` prints the funnel.
- `cd frontend && npm run build` compiles.

## Done when
- The page top shows the throughput funnel + red "0 of 20 will send today —
  blocker: no reviews" verdict for today's run.
- The unblock panel lists the held firms with a working inline Paste-reviews
  (which auto-extracts) and a Re-run now button.
- The false ALLOW_SEQUENCE_SEND / "human approval" / "3 senior contacts" copy is
  gone, replaced with accurate autonomous-send status.
- Backend endpoint + CLI + docs/cli.md row added; frontend builds.
