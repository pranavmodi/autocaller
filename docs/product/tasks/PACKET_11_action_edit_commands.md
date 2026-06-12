# Packet 11 — Action cancel/reschedule + pre-filled draft editing

You are the implementer in /home/pranav/autocaller (Possible OS). Complete the
operator contract for scheduled email actions: cancel, reschedule, and an
$EDITOR-prefilled edit-and-schedule flow.

## Read first
- app/services/action_execution.py (action lifecycle, statuses) and
  app/services/action_scheduler.py (due loop, expiry) — packet 10's work
- app/services/scheduled_time.py (PT/ISO parsing — reuse, do not duplicate)
- app/cli.py: `actions` group (send-approved-lead-gen-draft, list --scheduled,
  scheduler-status) and `lead-gen` group (show)
- app/api/actions.py (existing action endpoints)
- lead_gen_batch_items.reason_json['agent_draft'] carries composer drafts;
  reason_json may also carry send_email_action_id once scheduled

## Tasks
1. **`actions cancel <action_id> [--reason TEXT]`**: cancel an action in
   status waiting_for_approval or approved (incl. scheduled). Sets
   status='cancelled', records reason + actor in error/event timeline. Refuses
   (clear message) for running/succeeded/failed/cancelled. REST endpoint +
   CLI.
2. **`actions reschedule <action_id> --at <time>`**: change scheduled_for on
   an approved scheduled action (same time grammar as --at elsewhere: ISO or
   "HH:MM PT", past times rejected). Prints old → new in PT + UTC. Refuses
   for non-approved or unscheduled actions. REST + CLI.
3. **`lead-gen edit-draft <batch_item_id> [--at <time>] [--editor/--no-editor]`**:
   - loads the item's current draft (reason_json.agent_draft subject/body;
     if a scheduled action already exists via send_email_action_id, prefer
     the action's current subject/body)
   - opens $EDITOR (fall back to vi) on a temp file:
     first line `Subject: ...`, blank line, then body — same convention as
     git commit editing; `--no-editor` skips editing (use current text as-is)
   - on save: if the item already has a live scheduled action, update that
     action's subject/body (and scheduled_for if --at given) instead of
     creating a duplicate; otherwise create an approved action via the
     existing send-approved-lead-gen-draft path (with --at if given,
     immediate-execute only with an explicit --execute flag, default
     no-execute)
   - sync the item's reason_json.agent_draft (subject/body,
     operator_edited=true, scheduled_for_pt/utc) and
     approval_status='approved' so the lead-gen UI stays consistent —
     reuse one shared helper for this sync, called by edit-draft and by
     anything else that mutates a scheduled draft
4. **Events**: cancel/reschedule/edit each append to the action event
   timeline (visible in `actions show`).
5. **Tests**: cancel happy+refusal paths, reschedule time validation,
   edit-draft sync helper (UI-consistency fields), duplicate-prevention
   (editing an item with live action updates, not creates). Mock $EDITOR
   with a script that rewrites the temp file.
6. **Docs per golden rule**: docs/cli.md §3 rows + §10 recipe ("edit and
   reschedule a queued draft"); update .claude/skills/autocaller/SKILL.md and
   sync /root/.openclaw/workspace/skills/autocaller/SKILL.md.

## Constraints
- NO git commits; NO daemon restarts (orchestrator handles, active-call gated).
- Do NOT touch uncommitted master-agent WIP (app/services/master_agent*.py,
  frontend/app/agents/page.tsx, tests/test_master_agent_runner.py,
  docs/MASTER_AGENT_*.md).
- There are 10 LIVE approved scheduled actions for batch
  252d7499a8494001b0854bd521ca4b11 sending today from 16:30 UTC — do not
  modify, execute, or cancel them; validate only on actions you create with
  far-future times and clean up after yourself.
- No new dependencies.

## Validation (include output)
- New tests green + `pytest -q` full suite not broken.
- Demo transcript: create a far-future scheduled test action (existing
  send-email --at path, no execute), reschedule it, cancel it; show
  `actions show` event timeline reflecting all three. Clean up.
- `npm --prefix frontend run build` only if you touched frontend (UI changes
  not required this packet).

## Done when
Operator can cancel, reschedule, and $EDITOR-edit any queued draft from the
CLI without SQL, with the lead-gen UI staying in sync.
