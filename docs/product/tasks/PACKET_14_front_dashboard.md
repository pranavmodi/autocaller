# Packet 14 — /front dashboard: observability for the Front lead engine

You are the implementer in /home/pranav/autocaller. Packet 13 (deployed)
created front_contacts, front_firm_activity, front_sync_state, warm scoring,
and the `front` CLI group. Build the observability dashboard on top.

## Read first
- app/services/front_sync.py (status payloads, warm score fields)
- app/cli.py `front` group (status/contacts/warm-list shapes)
- frontend/app/lead-gen/page.tsx + frontend/components/Nav.tsx (conventions)
- frontend/lib/api.ts

## Tasks
1. **API** (new router or extend): `GET /api/front/status` (sync state,
   cursors, watermarks, last-run stats, table counts, day-over-day deltas),
   `GET /api/front/warm-list?limit=` (top firms by warm score: firm name,
   pif match, last_referral_at, last_seen_at, contact_count, named contacts
   w/ titles + emailed-before flag, tech_signals), `GET
   /api/front/contacts?domain=&q=&limit=`, `GET /api/front/signals`
   (tech-stack counts, inbox-activity mix, suppress-flagged firms).
2. **Page `/front`** + Nav entry, five zones:
   - Sync health strip: last run, calls used vs budget, watermark ages,
     next daily run, last error (red if stale >36h)
   - Funnel: contacts → domains → matched firms → firm_contacts added →
     warm-list size, with deltas
   - Warm list table (the core): sortable by warm score; each row expands to
     named contacts; "Create batch" button on selected rows → POST existing
     /api/lead-gen/batches flow is NOT right (it self-selects) — instead
     create batch+items directly via a new POST /api/front/warm-batch
     {domains:[...]} that builds a lead_gen_batch with reason_json basis
     'front-warm' (mirror the manual batch shape from batch
     252d7499a8494001b0854bd521ca4b11), returning batch id + link to
     /lead-gen
   - Timing feed: this week's referrers + domains first-seen <30d
     ("onboarding moments"), chronological
   - Signals panel: tech-stack breakdown, suppress list (collections/
     non-payment tagged domains if present in activity data)
3. **CLI parity**: `front warm-batch --domains a.com,b.com` (same endpoint);
   docs/cli.md rows + recipe; SKILL.md update (orchestrator syncs openclaw
   copy).
4. **Tests**: warm-batch creation (items shaped like the manual batch),
   status payload math (deltas), API smoke tests.

## Constraints
- NO commits, NO daemon restarts, NO Front API calls (read our tables only).
- Do NOT touch master-agent WIP files.
- Frontend validated by `npm --prefix frontend run build` only.
- One live scheduled action exists (Gary Guillen retry, 16:30 UTC) — leave it
  alone.

## Validation (include output)
- pytest new tests green + full suite not broken; npm build passes.
- curl each endpoint against the live daemon (read-only ones) and show
  abbreviated JSON with real synced data.
- Do NOT actually create a warm-batch against the live DB except one with a
  clearly-marked name 'TEST-packet14' — and delete it after.

## Done when
/front renders sync health, funnel, warm list with create-batch, timing feed,
and signals from real synced data; CLI/API/docs complete.
