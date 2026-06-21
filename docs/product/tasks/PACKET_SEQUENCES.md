# Packet: 3-step email sequences for daily lead-gen (behind a flag)

## Repo
Possible OS daemon (FastAPI + Typer), working dir IS the repo root
(/home/pranav/possibleos). Python, async SQLAlchemy (asyncpg), tests via pytest
in `.venv` (`source .venv/bin/activate`). Do NOT touch any other repo.

## Goal
Turn each new first-touch lead-gen email into a 3-step sequence (step 1 now,
step 2 +3 days, step 3 +7 days from start). The sequence engine ALREADY EXISTS
and is wired — the only gap is that the daily pipeline never starts a sequence.
This must be gated by a flag and default OFF (flag off = byte-for-byte current
behavior). No DB schema changes (EmailSequenceRow already has every column).

## What already exists (read these first; do NOT rebuild them)
- `app/db/models.py` `EmailSequenceRow`: status, current_step, steps_total,
  variant, last_sent_at, next_step_due_at, paused_reason; invariant "<=1 sequence
  per (contact, template)".
- `app/services/sequence_scheduler.py`: `start_sequence(...)` (creates a row at
  current_step=0), `sequence_loop` tick that picks due rows
  (`next_step_due_at <= now`, status='active'), composes the NEXT step, creates an
  operator approval draft, advances state. It is already started in
  `app/main.py` lifespan. Per-step send is gated by `ALLOW_SEQUENCE_SEND`.
- `app/services/sequences/possible_minds_dynamic.py`: `steps_total()` returns 4,
  `cadence_for()` returns `[0, 3, 7, 14]` (absolute day offsets from start), with
  per-step `STEP_OBJECTIVES`.
- Reply-stop ALREADY works: `app/services/inbound_email.py` (~line 524) sets the
  sequence `status='paused'`, `paused_reason='zoho_email_reply:<id>'` on a reply.
  Do not change this.
- `app/services/action_execution.py` `execute_action(action_id, ...)` (~line
  1345) is where a `send_email` action runs; on success it writes
  `execution_result_json`. Lead-gen sends are `action_type == 'send_email'`,
  `input_json.mode == 'lead_gen'`, with `input_json.batch_item_id`,
  `input_json.contact_id`, `input_json.composer_variant_key`.

## Implement

### 1. Flag
Add `SEQUENCES_ENABLED` (env, default off; treat "1"/"true"/"yes"/"on" as on).
Put a small helper, e.g. `sequences_enabled()`, in `sequence_scheduler.py`.
Add it to `.env.example` with a comment. Flag OFF => no sequence is ever
created and nothing else changes.

### 2. Make the dynamic template a 3-step sequence
In `possible_minds_dynamic.py`: `steps_total()` -> 3 and `cadence_for()` ->
`[0, 3, 7]`. Keep STEP_OBJECTIVES sensible for steps 1-3 (1: opener+pain,
2: bump/reframe, 3: low-pressure close). Make the count/cadence overridable via
optional env (`SEQUENCE_STEPS`, `SEQUENCE_CADENCE_DAYS="0,3,7"`) but default to
3 / [0,3,7].

### 3. Start the sequence when a first-touch send SUCCEEDS (the only real wire)
At the end of the successful-send path in `execute_action` (after
`execution_result_json` is set for a `send_email` `mode=='lead_gen'` action),
when `sequences_enabled()` is true:

- Compute `contact_id = input_json.contact_id`,
  `template_key = 'possible_minds_dynamic'`,
  `variant_key = input_json.composer_variant_key`.
- If an `EmailSequenceRow` already exists for (contact_id, template_key), do
  nothing (idempotent — this also means follow-up step sends won't create a
  second sequence).
- Otherwise create ONE `EmailSequenceRow` representing "step 1 already sent":
  - `current_step = 1`  (NOT 0 — step 1 was just sent by the pipeline; the
    scheduler must resume at step 2 and never re-send step 1)
  - `steps_total = 3`
  - `status = 'active'`
  - `last_sent_at = <the send timestamp>`
  - `next_step_due_at = <send timestamp> + (cadence[1] - cadence[0]) days`
    (i.e. +3 days for step 2)
  - `template_key`, `variant` (reuse the action's composer_variant_key if the
    column accepts it; else the template default), `started_by='lead_gen_daily'`
- Add a small helper in `sequence_scheduler.py` for this (e.g.
  `ensure_sequence_after_first_touch(contact_id, template_key, sent_at,
  variant)`) rather than overloading `start_sequence` (whose v1 contract is
  current_step=0). Keep the (contact, template) uniqueness guard.
- Failures here MUST NOT fail the send: wrap in try/except and log; the email
  already went out.

### 4. Steps 2-3 need no new code
`sequence_loop` already picks the row up at `next_step_due_at`, composes
step `current_step+1` (=2, then 3) via the dynamic composer, and creates an
operator approval draft. Confirm (read, do not rewrite) that it advances
current_step and stops at `current_step == steps_total`.

## Out of scope (do NOT implement here; leave TODO notes only)
- Daily-budget reservation for due follow-ups.
- Extra stop conditions beyond reply (bounce / booked-consult / unsubscribe).
- Auto-approval of follow-up steps.

## Constraints
- Flag OFF = zero behavior change (verify).
- No DB migration / no new columns.
- Idempotent: never create a 2nd sequence for the same (contact, template).
- Never re-send step 1.

## Verify (you must run these)
- `source .venv/bin/activate && python -c "import app.main"` imports clean.
- `python -m pytest tests/ -q -k "sequence or lead_gen or composer"` passes (run
  the relevant subset; fix anything you broke).
- Add a focused test: with `SEQUENCES_ENABLED=1`, simulating a successful
  first-touch `send_email mode=lead_gen` creates exactly one EmailSequenceRow
  with `current_step==1`, `steps_total==3`, `next_step_due_at` ~3 days out; a
  second successful send for the same contact creates no duplicate; with the flag
  off, no row is created.
- Do NOT commit unless tests pass; if you commit, scope the message clearly and
  do NOT push.
