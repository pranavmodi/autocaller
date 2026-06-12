# Packet 13 — Front lead engine: contacts sync, firm activity, warm scoring, egress guard

You are the implementer in /home/pranav/autocaller. Goal: person-level
identity + freshness from Precise Imaging's Front instance feeding contact
selection, with a PHI egress guard on all outreach. Full design rationale:
long-response.md (2026-06-11 version) and docs/product/BUSINESS_CONTEXT.md.

## Read first
- /root/.openclaw/workspace/secrets/front_precise.env (FRONT_AUTH_TOKEN,
  FRONT_API_BASE_URL) — production Precise instance, treat with care
- /root/.openclaw/workspace/scripts/bulk_crawl_tracked.py — pacing/checkpoint
  conventions to mirror (do NOT modify it)
- app/services/contact_selection.py (scorer), lead_gen_cybernetic.py (policy
  versions, ensure_default_policy), action_execution.py (policy checks list
  in the send gate), pifstats_sync.py (external-sync service pattern)
- app/db/models.py, alembic/ conventions

## Build order (egress guard FIRST)

### 1. Egress guard: `no_patient_data_in_outreach`
New policy check in the send-action policy gate (alongside
consult_link_present etc.), for lead_gen email actions:
- deterministic layer: regex for DOB patterns (MM/DD/YYYY near "DOB"),
  MRN/case-number shapes, "DOL <date>", patient-context phrases
- LLM layer: one gateway call (model "openclaw" via llm_gateway) on the FINAL
  rendered subject+body asking strictly: does this contain any patient name,
  DOB, medical detail, or case-specific patient information? JSON yes/no +
  reason. Fail CLOSED: LLM error/timeout = check fails (deterministic-only
  pass is not sufficient on error).
- cache result by body hash so retries don't re-call the LLM.
- Tests: seeded PHI bodies must fail; today's clean drafts' style must pass;
  LLM mocked in tests.

### 2. Schema (alembic, additive)
Tables per the design: `front_contacts` (front_id PK, name, handles jsonb,
primary_email, domain, first_synced_at, front_updated_at, raw_json),
`front_firm_activity` (domain PK, pif_id nullable, contact_count,
last_seen_at, last_referral_at, last_records_at, inbox_breakdown jsonb,
tech_signals jsonb, synced_at), `front_sync_state` (key PK, cursor,
watermark, updated_at). Columns on firm_contacts: front_contact_id,
front_last_seen, tech_signals jsonb (all nullable).

### 3. `app/services/front_sync.py`
- httpx client, creds from the secrets env file (load via dotenv path, never
  hardcode), **hard rate budget: max_calls per run (default 300), min 1.5s
  between calls, stop cleanly at budget and persist cursor**.
- `sync_contacts(max_calls)`: paginate GET /contacts (limit=100), upsert
  front_contacts, derive domain from primary handle, watermark on
  front_updated_at for incremental runs.
- `sync_inbox_activity(max_calls)`: for inbox ids in config
  (default: inb_qfq9 Scheduling & Orders, inb_rcld Records & Images,
  inb_37vb5 AR Case Updates): GET /inboxes/{id}/conversations paginated since
  watermark; store ONLY metadata aggregates into front_firm_activity
  (match participant/recipient handles' domains; update last_referral_at for
  Scheduling, last_records_at for Records, last_seen_at all). Do not store
  bodies.
- `resolve_firms()`: no API calls. Match front domains to MC pif_firms
  (sqlite at /root/.openclaw/workspace/mission-control/data/mission.db,
  read-only: website domain + emails column); write pif_id into
  front_firm_activity; upsert matched people into firm_contacts
  (source='front', front_contact_id, front_last_seen, email, name; skip
  consumer domains gmail/yahoo/etc and *.filevineapp.com robot addresses —
  but RECORD filevine pattern as tech_signals {"case_mgmt":"filevine"} on
  the firm).
- `refresh_warm_scores()`: no API calls. Compute warm score
  (recency decay on last_referral_at/last_seen_at × log(1+contact_count) ×
  seniority from title × small tech-match bonus) and store on
  front_firm_activity; integrate into contact_selection as a new weighted
  feature read from these tables; create policy version 'lead-gen-v2'
  (copy of v1 + front_warmth weight) but DO NOT activate it — orchestrator
  activates after review.
- Daemon loop `front_sync_loop()` (daily, same pattern as other loops in
  app/main.py): contacts → activity → resolve → score, budget-capped.

### 4. CLI (golden rule)
`front sync [--full] [--max-calls N]`, `front status` (cursors, watermarks,
counts, last run), `front contacts [--firm|--domain]`, `leads warm-list
[--limit 20]` (top firms by warm score with named contacts not yet emailed).
docs/cli.md §3 rows + §10 recipe ("daily warm list"); update
.claude/skills/autocaller/SKILL.md (orchestrator syncs the openclaw copy).

### 5. Tests
Egress guard (PHI seeded fail / clean pass / LLM-error fails closed),
domain derivation + consumer-domain skip, filevine tech_signal extraction,
warm score math, watermark incrementality (mock httpx for all Front calls),
selection integration reads the new feature.

## Constraints
- **Front API: during validation you may make at most 15 REAL calls, paced
  ≥2s, read-only GETs** (e.g. one contacts page, one inbox page). The full
  backfill is orchestrator-run. Never POST/PATCH to Front.
- NO commits, NO daemon restarts. Do NOT touch master-agent WIP files. Do NOT
  touch the 10 live scheduled actions for batch 252d7499 (they begin sending
  16:30 UTC — your work must not interfere with the scheduler loop).
- MC sqlite is read-only for you; busy_timeout when reading.
- Additive migrations only. No new deps (httpx, dotenv present).

## Validation (include output)
- pytest: new tests green, full suite not broken.
- `front sync --max-calls 10` real run: a page of contacts lands in
  front_contacts; cursor persisted; show counts + 3 sample rows (mask emails
  to first 2 chars in output).
- `resolve_firms` on those rows: ≥1 domain matched to a pif_firm; filevine
  handles produce tech_signals and are excluded from firm_contacts upserts.
- Egress guard: run policy-check (no execute) against a synthetic action with
  a PHI-laden body → fails with this check named; against one of today's
  final draft bodies (copy text, do NOT touch the live action) → passes.
- `leads warm-list` prints something sensible from synced data.

## Done when
Contacts + activity sync run budgeted and resumable; warm scores feed
selection behind an unactivated lead-gen-v2 policy; egress guard blocks PHI at
the send gate; CLI + docs complete; the orchestrator can run the full
backfill by repeating `front sync` runs.
