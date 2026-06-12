# Packet 12 — Auto-observations: every outreach event writes to the learning loop

You are the implementer in /home/pranav/autocaller. Context: the cybernetic
lead-gen loop has 3 observations ever vs 178 emails sent — Observe is severed
from Act. Goal: every meaningful event writes a `lead_gen_observations` row
automatically, no human in the path. 10 scheduled emails send TODAY starting
16:30 UTC — their events must be captured by this work.

## Read first
- app/services/lead_gen_cybernetic.py: classify_and_store_observation, the
  observations table usage (lead_gen_observations), `lead-gen observe` CLI
- app/services/action_execution.py: execute path for send_email /
  send_approved_lead_gen_draft actions (where success/failure is known)
- app/services/inbound_email.py + lead_feedback_classifier.py: how replies
  get matched to contacts/batches and classified
- app/services/resend_webhooks.py and link_events table (click tracking)
- app/services/calcom_service.py / consult_bookings (booking events)
- docs/LEAD_GEN_CYBERNETIC_TECHNICAL.md (current observation contract)

## Design rule
One helper: `record_observation(event_type, raw_event, *, contact_id=None,
batch_id=None, batch_item_id=None, classification=None)` — deterministic
events store directly with a deterministic classification (no LLM); only
genuine replies go through the existing LLM classifier. Idempotent: a
(event_type, dedupe_key) repeat must not create duplicate observations — add
a dedupe_key column or use raw_event hash, whichever fits the existing table
with a nullable additive migration.

## Events to wire (each with contact/batch linkage when derivable)
1. `email_sent` — on successful execution of lead-gen email actions
   (immediate AND scheduled paths share execute_action — hook once).
   Include action id, subject, brief_version, composer keys.
2. `email_send_failed` — failed execution (transport error, policy refusal at
   execution time).
3. `email_reply_received` — when an inbound email is matched to a contact:
   store observation and run the existing LLM feedback classifier
   (classification into the observation). Hook where matching already
   happens; do not build new polling.
4. `link_clicked` — when link_events rows are attributed to a tracked send.
5. `consult_booked` — when a Cal.com booking lands (consult_bookings insert
   path).
6. `call_disposition` — when the judge/disposition pipeline finalizes an
   outbound call outcome for a firm contact (event includes outcome).
7. `email_action_cancelled` / `email_rescheduled` — from packet-11 lifecycle
   (cheap, completes the audit trail).

## CLI + visibility (golden rule)
- `lead-gen observations [--since 7d] [--type X] [--contact ...] [--json]` —
  list observations with linkage.
- `lead-gen observations summary [--since 7d]` — counts by event_type — this
  is the weekly learning-KPI readout (qualified engagements/week).
- docs/cli.md §3 rows + §10 recipe ("read the week's feedback"); update both
  SKILL.md copies (.claude/skills/autocaller + sync to
  /root/.openclaw/workspace/skills/autocaller/).
- docs/LEAD_GEN_CYBERNETIC_TECHNICAL.md: document the auto-observation
  contract and event taxonomy.

## Constraints
- NO commits, NO daemon restarts (orchestrator handles; active-call gated).
- Do NOT touch uncommitted master-agent WIP (app/services/master_agent*.py,
  frontend/app/agents/page.tsx, tests/test_master_agent_runner.py,
  docs/MASTER_AGENT_*.md).
- 10 LIVE scheduled actions exist for batch 252d7499... — do not execute,
  modify, or cancel them. Validate hooks with synthetic/test events only.
- LLM calls only via existing classifier path, only for reply classification,
  and none during tests (mock it).
- Additive nullable migrations only.

## Validation (include output)
- New tests: each event type creates exactly one observation; idempotency
  (same event twice → one row); reply path calls classifier (mocked);
  scheduled-execution path records email_sent (use a fake transport).
- Full `pytest -q` not broken.
- `lead-gen observations summary` runs against the real DB and prints counts
  (will be near-zero now — that's fine, today's sends will populate it).

## Done when
Every send/failure/reply/click/booking/disposition writes a linked observation
automatically; the weekly KPI is one CLI command; today's 10 sends will be
captured without any further wiring.
