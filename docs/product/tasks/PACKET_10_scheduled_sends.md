# Packet 10 — Scheduled email sends: CLI sets time, daemon executes when due, UI shows it

You are the implementer in /home/pranav/autocaller (Possible OS). Operator
need: create approved lead-gen email drafts scheduled for specific PDT morning
times from the CLI, see drafts + scheduled times in the UI, and have the
daemon send them when due.

## Read first
- app/db/models.py:500 — `agent_actions.scheduled_for` already exists
  (timestamptz, nullable); serialized by action_execution.py. Nothing sets,
  executes, or displays it.
- app/services/action_execution.py — create_send_email_action, policy gate,
  the execute path used by `actions execute-approved-lead-gen`
- app/cli.py — `actions send-approved-lead-gen-draft` and `actions send-email`
  commands; how `serve` wires background loops (judge loop etc.) — find the
  daemon startup (lifespan/serve) and copy that pattern
- frontend/app/actions/ — the actions UI page
- CLAUDE.md — golden rule (CLI parity + docs/skill updates) and the
  "never auto-start the dispatcher" principle (see constraint below)

## Tasks
1. **CLI scheduling**: add `--at <time>` to `actions send-approved-lead-gen-draft`
   and `actions send-email`. Accepts ISO-8601 with offset
   ("2026-06-11T09:30:00-07:00") and a convenience form "HH:MM PDT|PST|PT"
   (today in America/Los_Angeles; if already past, error — do not silently
   roll to tomorrow). With `--at`: create the action with status approved and
   `scheduled_for` set, run the policy check, DO NOT execute; print the
   scheduled time in both PT and UTC. Without `--at`: behavior unchanged.
2. **Due-action scheduler**: a small async loop in the daemon (same pattern as
   existing background loops) that every 30s executes actions where
   status='approved' AND scheduled_for IS NOT NULL AND scheduled_for <= now(),
   oldest first, one at a time, through the existing policy-gated execute
   path. Mark normal success/failure exactly as immediate execution does.
   Add `actions scheduler-status` CLI (running? last tick? pending count) and
   include pending-scheduled count in `actions list` header or summary.
3. **Safety**: executing *approved + explicitly scheduled* actions on boot is
   acceptable (unlike the dispatcher rule) BUT: skip actions whose
   scheduled_for is more than 24h in the past (mark status='expired' with
   error note instead of sending stale outreach), and respect every existing
   policy gate on each execution.
4. **UI**: actions page shows scheduled_for (PT + relative "in 2h 14m") on
   list rows + detail; visually distinguish scheduled-pending
   (clock icon/badge) from immediate. Drafts (subject/body in input_json)
   must be readable in the detail view if they aren't already.
5. **CLI list filter**: `actions list --scheduled` shows only future-scheduled
   actions ordered by scheduled_for.
6. **Tests**: time-parse (ISO, "9:30 PDT", past-time error), due-selection
   query (due vs future vs expired), and one end-to-end-ish test of the
   scheduler tick executing a fake approved action (mock the transport).
7. **Docs per golden rule**: docs/cli.md §3 rows + a §10 recipe ("schedule a
   morning send window"); update .claude/skills/autocaller/SKILL.md AND sync
   to /root/.openclaw/workspace/skills/autocaller/SKILL.md.

## Constraints
- NO git commits; NO daemon restarts (orchestrator does both; restart is
  gated on an active-call check).
- Do NOT touch the uncommitted master-agent WIP (app/services/master_agent*.py,
  frontend/app/agents/page.tsx, tests/test_master_agent_runner.py,
  docs/MASTER_AGENT_*.md).
- No new dependencies; use zoneinfo for PT handling.
- Run your new tests + a quick `pytest -q` smoke; include output.

## Validation (include output)
- Unit tests green; full suite not broken.
- `actions send-email --to test@example.com ... --at "<future ISO>"` (with
  whatever no-send/test gates exist) creates an approved scheduled action and
  prints PT+UTC; `actions list --scheduled` shows it; show its JSON with
  scheduled_for set. Do NOT send real email.
- Frontend `npm run build` (or the repo's build command) passes.

## Done when
Operator can run one CLI command per draft with --at "09:30 PT", see them
queued with times in /actions, and the daemon sends each within 30s of its
scheduled time — all policy-gated.
