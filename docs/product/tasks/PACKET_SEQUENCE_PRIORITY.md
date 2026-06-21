# Packet: Prioritize due follow-ups over fresh leads in the daily run (strict, within the 20/day quota)

## Repo
Possible OS daemon at /home/pranav/possibleos (working dir IS repo root). Python,
async SQLAlchemy (asyncpg), pytest in `.venv`. Do NOT touch any other repo.

## Goal
Make the daily lead-gen run the single owner of the daily email quota and spend
it **due follow-ups first, then fresh leads** (strict: fresh gets only the
remainder, possibly 0). Gate all new behavior behind the existing
`SEQUENCES_ENABLED` flag (default off => current fresh-only behavior, byte for
byte). No DB schema changes.

## Context you must read first (do not rebuild these)
- `app/services/lead_gen_daily.py`: the checkpointed daily pipeline.
  `batch_size = daily_batch_size` (default 20). The select stage
  (`_select_contacts` -> `recommend_sequence_contacts`) picks ONLY fresh
  first-touch contacts up to `batch_size`. `_compose_batch` composes the batch
  items into approval-waiting `send_email mode=lead_gen` actions.
- `app/db/models.py` `EmailSequenceRow`: status, current_step, steps_total,
  variant, last_sent_at, next_step_due_at, paused_reason, contact_id,
  template_key.
- `app/services/sequences/possible_minds_dynamic.py`: 3 steps, `cadence_for()`
  = `[0,3,7]` (absolute day offsets). Per-step objectives in STEP_OBJECTIVES.
- `app/services/sequence_scheduler.py`: `sequences_enabled()`,
  `ensure_sequence_after_first_touch()` (creates step-1 sequence on first-touch
  send), and the autonomous `sequence_loop`/`tick` that drafts due steps (gated
  by `ALLOW_SEQUENCE_SEND`). The composer is `compose_lead_email(contact,
  firm_name, sequence, step_num, ...)`.
- `app/services/action_execution.py` `execute_action(...)`: on a successful
  `send_email mode=lead_gen` send it already calls
  `ensure_sequence_after_first_touch(...)` (step 1). `payload` is the action
  input_json; `result` is the execution result (`result.get("sent_at")`).
- Reply-stop: `inbound_email.py` pauses the sequence on a reply. Do not change.

## Implement (all gated by `sequences_enabled()`)

### 1. Daily-run allocation: follow-ups first, then fresh
In the daily select/batch stage, when `sequences_enabled()`:
1. Load **due follow-ups**: `EmailSequenceRow` where `status='active'` and
   `next_step_due_at <= now`, ordered by `next_step_due_at ASC` (oldest first),
   limit `batch_size`. Resolve each to its `FirmContactRow` + firm_name.
2. Take up to `batch_size` of them as the first batch items, `action_type =
   'follow_up'`, storing on the item's reason: `sequence_id`, `step_num =
   current_step + 1`, and the contact/firm.
3. Fresh fill: select `max(0, batch_size - len(followups))` fresh first-touch
   contacts via the existing `_select_contacts` path. (Strict: 0 fresh when the
   follow-up backlog >= batch_size.)
4. Compose ALL items (follow-ups + fresh) into approval-waiting `send_email
   mode=lead_gen` actions, exactly like today. For follow-up items, compose with
   `step_num = current_step + 1` so the composer uses follow-up framing.
5. **Claim** each follow-up sequence so the autonomous scheduler does not also
   draft it: when its step is drafted, set the sequence out of the active+due
   pool (mirror the scheduler's existing claim — e.g. `status='paused'`,
   `paused_reason='awaiting_operator_send_approval'`, `next_step_due_at=None`).
   It will be advanced/reactivated by the send-hook in step 2.

Record counts in the run's select-stage output: `followups_selected`,
`fresh_selected`, `followups_due_total`.

### 2. Send-hook: advance the sequence on follow-up send
In `execute_action`'s lead-gen send-success block (where
`ensure_sequence_after_first_touch` is already called), ALSO handle follow-up
sends. After a successful `send_email mode=lead_gen` send, if an
`EmailSequenceRow` exists for `payload.contact_id` + template:
- If the send corresponds to a follow-up step (the sequence is not brand new /
  current_step >= 1 and a step was claimed): set `current_step = step_just_sent`,
  `last_sent_at = sent_at`. If `current_step >= steps_total`: `status='completed'`,
  `next_step_due_at=None`. Else: `status='active'`,
  `next_step_due_at = sent_at + (cadence[current_step] - cadence[current_step-1])
  days`, `paused_reason=None`.
- Keep `ensure_sequence_after_first_touch` for the true first touch (no existing
  sequence). Make the two paths mutually exclusive and idempotent. Wrap in
  try/except so sequence bookkeeping never fails the send.

### 3. Keep one quota owner
The daily run is now the sole follow-up drafter. Ensure the autonomous
`sequence_loop` does not double-draft the daily-run-claimed sequences (claiming
in 1.5 already removes them from the active+due pool, so the existing scheduler
naturally skips them — verify this is true and add a guard/comment).

## Out of scope (leave TODO notes)
- "Reserve a floor for fresh" mode (we chose strict follow-ups-first).
- Stop-on-bounce/unsubscribe.

## Constraints
- `SEQUENCES_ENABLED` off => zero behavior change (verify).
- No DB migration.
- Never exceed `batch_size` total items/day. Never double-draft a step. Never
  re-send a step. Never resume a reply-paused sequence.

## Verify (you must run these)
- `source .venv/bin/activate && python -c "import app.main"` clean.
- `python -m pytest tests/ -q -k "sequence or lead_gen or composer"` passes; fix
  what you break.
- Add focused tests: with the flag on and N due follow-ups, the daily batch is
  followups-first then fresh, total == batch_size, fresh == max(0, batch_size-N);
  a successful follow-up send advances current_step and sets the next due date
  (or completes at the last step); flag off => fresh-only selection unchanged.
- Do NOT commit unless tests pass; if you commit, scope the message and do NOT
  push.
