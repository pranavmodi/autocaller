# PACKET — /lead-gen: show predicted send channel (Zoho/Resend) per draft

Workdir `/home/pranav/possibleos`. Orchestrator (Claude) reviews, builds the
frontend, restarts services, commits. **You do NOT restart services, build the
frontend, or commit.** Backend + frontend code + tests only.

## Why
Lead-gen sends now split across two transports (`zoho_first_then_resend`): the
first 20 approved sends of the day go via **Zoho** (daily cap 20), the rest
overflow to **Resend**. Operators reviewing drafts in `/lead-gen` should see
which channel each draft will go out on.

## How the channel is decided (reuse, don't reinvent)
It's a **global per-day** computation, not per-batch. For a given run date, take
all `approved` lead-gen `send_email` actions not yet started, **order by
`scheduled_for, id`**, and assign by the provider caps from
`app/services/lead_gen_transport.py` (`provider_daily_caps_from_weights`):
the first `zoho_api` cap → `zoho_api`, the next `resend` cap → `resend`, any
beyond total → none/over-budget. Already-sent rows keep their *actual*
`email_logs.transport`. Reuse the transport module's caps + strategy; don't
hardcode 20.

## Scope
1. **Backend — channel plan.** Add `daily_channel_plan(run_date=None) ->
   {batch_item_id: {"channel": "zoho_api"|"resend"|"over_budget"|"sent:<t>",
   "scheduled_for": ...}}` in `app/services/lead_gen_daily.py` (or transport
   module). Expose it: include a `predicted_transport` field per item in the
   existing `GET /api/lead-gen/batches/{batch_id}` response **and/or** a small
   `GET /api/lead-gen/daily-run/channel-plan?date=` endpoint the page can call.
   Respect strategy `resend_first_then_zoho` too (order flips).
2. **Frontend — badge.** In `frontend/app/lead-gen/page.tsx`, render a small
   channel badge on each draft row / in the preview + the "View all drafts"
   modal: **"Zoho"** vs **"Resend"** (and a muted "sent via <t>" once sent).
   Pull from the new field/endpoint via `frontend/lib/api.ts`. Keep it subtle
   (a pill), consistent with existing badges.

## Guardrails
- Touch only `app/services/lead_gen_daily.py` (or transport), `app/api/lead_gen.py`,
  `frontend/lib/api.ts`, `frontend/app/lead-gen/page.tsx`, `docs/`, `tests/`.
- Read-only display — **no change to sending/scheduling/approval logic**.
- No service restart, no `npm run build`, no commit (orchestrator does those).

## Validation (paste output)
- `python3 -m py_compile` changed Python; `cd frontend && npx tsc --noEmit` clean.
- A backend test: seed 40 approved sends for a day with caps {zoho:20, resend:20}
  and assert `daily_channel_plan` labels the first 20 (by scheduled_for) `zoho_api`
  and the next 20 `resend`.
- Note the exact JSON shape the frontend consumes.

## Finish
Report diff + validation. Orchestrator will `tsc`/build the frontend, restart,
and commit.
