# PACKET FIRMINTEL E1 — Combined two-pass enrichment + completeness gate (EmailTag)

Workdir: `/home/pranav/emailtag`. Source: `docs/MIGRATION_PLAN.md` (E1) and
`docs/FIRM_INTELLIGENCE_CONTRACT.md` §4 (firm_profile). **Depends on E0
(committed) and E0b merge applied** — enrichment runs on deduped firms only
(`merge_status='active'`).

You are Codex. **Build the enrichment runner + completeness gate. DO NOT run the
full backfill against production** (that is an operator/orchestrator step). Build
+ unit-test (mocked LLM/search) only.

## Why this design
Today enrichment is several separate analyzers, several making their own web/LLM
calls. Collapse into **two passes per firm** so the expensive web search runs
**once** and harvests many fields.

## Scope (build all)

### 1. Pass A — internal (no web calls)
Parse each firm's email/conversation corpus **once** and emit, from that single
parse (REUSE `email_analyzer`, `signature_extractor`, `icp_scorer`):
- `behavioral_data` (after_hours_ratio, sender_roles, primary_pain_point,
  monthly_email_volume, days_since_last_contact, topic_distribution,
  peak_contact_days, contact_profiles)
- leadership / people (signature extraction + role/persona detection)
- `icp_score` / `icp_tier` / `score_breakdown` (deterministic on behavioral)
Do not parse the corpus three times — share it across the three.

### 2. Pass B — external (ONE structured web-search call)
Instead of separate searches for website, firmographics, leadership, vendor
stack: **one `web_search_preview` call returning a single structured JSON**
(REUSE/consolidate `firm_researcher`):
- resolved `canonical_website` (reuse E0 resolver)
- firmographics: size_hint, practice areas / case_mix, metro/city/state
- public leadership (merge with Pass A)
- **`vendor_stack`** (case_mgmt: filevine/litify/casepeer/smartadvocate/evenup +
  others) — add the `vendor_stack` field/column to pif_info if missing (migration)
- competitive_context

### 3. Completeness gate
Compute and persist on pif_info:
- `profile_completeness` (int: count of core fields populated)
- `outreach_ready` (bool): true only when the **must-have** core fields are all
  present — `canonical_website`, ≥1 decision-maker w/ email+persona,
  `primary_pain_point`, `icp_tier`, behavioral_data, relationship recency — AND
  `profile_completeness >= 8`.
This is the gate possibleos selection will use ("8–12 data points before copy").

### 4. Batch runner
- Idempotent + **resumable** (skip already-enriched unless `--force`), rate-aware
  (cap web-search calls/min), processes `merge_status='active'` firms only.
- Dry-run/limited mode (`--limit N`, `--dry-run`) + a gated `--apply --yes`.
- Emit coverage metrics (how many firms now have each field / are outreach_ready).
- CLI in `scripts/` + a Celery orchestration task (research queue).

## Repo conventions
Reuse existing analyzers; Alembic migration for new columns; Celery + pytest.

## Guardrails (hard)
- **DO NOT run the full prod backfill.** Build, run on fixtures / `--limit` with
  mocks, unit-test only. No mass live LLM/web calls in this packet.
- **Soft writes:** fill blanks / update derived fields; never overwrite operator
  edits. Additive schema only; delete nothing.
- **Do NOT `git commit`/`git push`.** Orchestrator commits + runs the backfill.
- Rate-aware; no service restarts, no `/etc`, no Docker.

## Validation (run, report)
- `pytest test/ -k "enrich or completeness or vendor"` — all green.
- Test: one fixture firm → Pass A populates behavioral+leadership+icp from a
  single corpus parse (assert corpus parsed once via a call spy).
- Test: Pass B is **one** web_search call producing website+firmographics+
  vendor_stack+leadership (assert single search invocation, mocked).
- Test: `outreach_ready` flips true only when must-have fields present.
- `scripts/...enrich.py --dry-run --limit 5` prints a plan, zero writes.

## Report (end of run)
Files added/changed + migration id, the core-field list used for completeness,
how to run dry-run + tests, and STOP. Do not run the prod backfill; do not ship copy.
