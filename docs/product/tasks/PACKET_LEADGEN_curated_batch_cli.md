# PACKET LEADGEN — curated batch CLI (create + add-contacts + recount)

Workdir: `/home/pranav/possibleos`. Read first: `app/api/lead_gen.py`
(CreateBatchRequest, batch endpoints), the `lead_gen_batches` /
`lead_gen_batch_items` models, how `counts_json` is populated by the daily run
(`app/services/lead_gen_daily.py`), how the batch-detail API + frontend
`app/lead-gen/page.tsx` read `counts` and items, and `docs/cli.md` §lead-gen +
the CLI-parity golden rule in `CLAUDE.md`.

You are Codex. No commit/push/restarts. Additive only. Do NOT touch the send
scheduler, the daily-run pipeline, or any existing command's behavior.

## Why
Operators (human + AI) need to build **curated** lead-gen batches from an
explicit contact list — not only the auto-selected `recommend`/`daily-run`
batches. Today that requires raw SQL, which (a) violates CLI parity and (b)
skips the `counts_json` metadata the UI reads, so curated batches render as
"items -" and "Batch unavailable". Add first-class CLI + REST + service.

## Scope

### 1. Service (`app/services/lead_gen_curated.py`, new)
- `create_curated_batch(name, template_key='possible_minds_dynamic',
  target_metric='meetings_booked', created_by='operator', status='approved')`
  -> inserts a `lead_gen_batches` row with `counts_json =
  {"basis":"operator-curated","returned":0,"requested":0}` and the active
  `policy_version`. Returns the batch dict.
- `add_contacts_to_batch(batch_id, contact_refs, actor='operator')` where
  `contact_refs` is a list of contact ids and/or emails:
  - resolve each against `firm_contacts` (by id, else by email) to get
    firm_name, contact_email, contact_name, contact_title, persona, pif_id;
  - skip refs already in the batch (idempotent) and unresolvable refs
    (report them);
  - insert `lead_gen_batch_items` (approval_status='pending', template_key
    from batch, a minimal `reason_json = {"source":"operator-curated"}`,
    score null);
  - **recompute and persist `counts_json.returned` = live item count** on the
    batch (this is the fix for "items -"). Return {added, skipped, item_ids:
    [{contact_email, item_id}]}.
- `recount_batch(batch_id)` -> recompute `counts_json.returned` from the live
  item count; use to repair batches created before this packet. Preserve any
  existing counts_json keys; only set returned/requested.

### 2. REST (`app/api/lead_gen.py`)
- Reuse existing `POST /api/lead-gen/batches` for create IF it already sets
  counts; otherwise have it call `create_curated_batch` when a new
  `curated: true` flag is passed (keep old behavior default).
- `POST /api/lead-gen/batches/{batch_id}/add-contacts` body
  `{contacts: [id_or_email], actor}` -> `add_contacts_to_batch`.
- `POST /api/lead-gen/batches/{batch_id}/recount` -> `recount_batch`.

### 3. CLI (`app/cli.py`, under the existing `lead-gen` group)
- `lead-gen create-batch --name <name> [--template-key ...]
  [--target-metric ...] [--created-by ...] [--json]` -> prints the new
  batch_id (drives the REST create with curated=true).
- `lead-gen add-contacts <batch_id> (--contact <id|email> ... | --from <path>)
  [--json]` -> adds contacts; `--from` reads a file of one id/email per line
  or a JSON array; prints the added contact->item_id table (so the operator
  can then drive `actions send-approved-lead-gen-draft --item <id> ...` or
  `lead-gen schedule-drafts`). Drive the REST endpoint on loopback.
- `lead-gen recount <batch_id> [--json]` -> repair counts display.
- All three: REST on loopback (daemon is source of truth), matching how other
  `lead-gen` subcommands call the API.

### 4. Docs (golden rule)
- `docs/cli.md`: add the three commands to the §3 new-command reference table;
  add a §10 recipe "build and send a curated operator batch" showing the full
  flow: create-batch -> add-contacts -> send-approved-lead-gen-draft (or
  schedule-drafts) -> approve.
- `.claude/skills/possibleos/SKILL.md`: add the three commands to the lead-gen
  section. (Orchestrator syncs the openclaw copy.)

## Guardrails (hard)
- Additive only; existing `recommend`/`daily-run`/`email-agent-slice`/
  `schedule-drafts`/`send-approved-lead-gen-draft` behavior unchanged.
- Idempotent add (no duplicate items for the same contact in a batch).
- Do NOT `git commit`/`git push`; no service restarts; no scheduler changes.

## Validation (run, report)
- Unit/integration test (repo's pytest): create_curated_batch sets
  counts_json.returned=0; add_contacts_to_batch resolves by id and by email,
  is idempotent, and bumps counts_json.returned to the live count;
  recount_batch repairs a batch whose counts_json is empty.
- Live smoke on a temp batch (tag name 'TEST curated'): `lead-gen create-batch`
  -> `lead-gen add-contacts` with 2 real contact emails -> confirm the
  batch-detail API now returns counts.returned=2 and the items; then delete
  the temp batch rows. Report the before/after counts.
- Confirm an existing curated batch (id supplied by orchestrator) renders
  after `lead-gen recount`.

## Report (end of run)
Files changed, the three command signatures, the counts_json fix explanation,
test results, and STOP.
