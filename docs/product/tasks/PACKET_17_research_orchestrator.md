# Packet 17 — Firm-research orchestrator + contact persona mapper

You are the implementer in /home/pranav/autocaller. The PIF Stats API
(Precise's email-processing system, built by Possible Minds) already has
firm web-research, staff research, behavior analysis, and people search —
but only 95/1,711 firms have firm research and 1/1,711 staff research.
Autocaller only ever *pulls* (leads sync-pifstats); nothing *triggers*
research. Build the orchestrator that drives it warm-first, plus a persona
mapper that turns titles/behavior into the persona keys the composer skill
now consumes (see docs/product/PI_FIRM_PERSONAS.md and the persona section
in app/skills/possible-minds-lead-email-composer/SKILL.md).

## Read first
- app/services/pifstats_sync.py (existing API client conventions, PIF_BASE)
- API surface: GET https://emailprocessing.mediflow360.com/api/v1/openapi.json
  Key endpoints: POST /pif-info/{pif_id}/research, POST /pif-info/{pif_id}/
  research-staff, POST /pif-info/{pif_id}/analyze-behavior,
  GET /pif-info/research-status/{task_id}, GET /pif-info/{pif_id},
  GET /pif-info/people. No auth header is currently required (verify; if it
  starts requiring auth, read creds from env, never hardcode).
- app/services/front_sync.py (FrontRateBudget pattern — copy the budget +
  429 handling approach), competitor_graph.py (persona-rule style)
- app/db/models.py firm_contacts (front_contact_id, tech_signals already
  added), lead_gen_batch_items.persona (the consumer)
- docs/product/PI_FIRM_PERSONAS.md (canonical persona inventory)

## Build

### 1. Schema (alembic, additive)
- `research_tasks` (task_id varchar PK, pif_id varchar, kind varchar
  ['research','research_staff','analyze_behavior'], status varchar,
  requested_at, completed_at timestamptz NULL, result_summary jsonb NULL)
- firm_contacts new columns (nullable): `persona varchar(32)`,
  `persona_source varchar(32)`, `persona_confidence float`,
  `research_title varchar(255)`, `linkedin_url` exists already — check.

### 2. `app/services/firm_research.py`
- PifStatsClient: httpx, base from PIF_BASE env-overridable, hard budget
  (default max 30 task-creating POSTs per run, >=2s spacing, 429-aware
  like FrontClient), GETs cheap but still paced >=0.5s.
- `queue_firm_research(pif_id, *, staff=True, behavior=True)` → POST
  research (+ research-staff + analyze-behavior), insert research_tasks
  rows. analyze-behavior is verified working and valuable: it returns
  (on the firm record's `behavioral_data` after completion) e.g.
  `{"after_hours_ratio": 0.714, "primary_pain_point": "lien_negotiation",
  "topic_distribution": {...}, "sender_roles": {...}, "peak_contact_days":
  [...], "monthly_email_volume": [...]}`. Sync this dict into a new
  nullable jsonb column `behavioral_json` on front_firm_activity (keyed
  via the firm's domain) AND make the lead-gen composer payload include it
  under `front_signals.behavior` so drafts can use after-hours ratios and
  primary pain points as evidence (find where front_signals is assembled
  in lead_gen_email_agent.py / its payload builder).
- `poll_research_tasks()` → for queued/running rows, GET research-status,
  update status; on completion fetch GET /pif-info/{pif_id} and upsert:
  - leadership[] and staff[] entries → firm_contacts (match by email when
    present, else name+pif_id; source='pif_research'; store title in
    research_title; keep existing rows, update titles/phones/linkedin)
  - store the raw firm payload summary in research_tasks.result_summary
    (counts, not the whole blob).
- `orchestrate_warm_research(top_n=50, kinds=...)`: walk
  front_firm_activity warm-score order, join to known pif_id, skip firms
  already researched (a completed research_tasks row of that kind OR
  pre-existing titled leadership), queue up to the budget, then poll loop
  until done or timeout (30min cap), then run persona mapping.
- NO daemon loop in this packet — operator/CLI-triggered only (research
  costs LLM+web work on Precise production infra; cadence is a later
  decision).

### 3. `app/services/persona_mapper.py`
- Persona keys (must match composer skill): founder_owner,
  managing_partner, coo_ops, intake, records, case_manager,
  lien_settlement, marketing, attorney, paralegal.
- `classify_contact(title, email, name) -> (persona|None, source, confidence)`
  precedence: research_title/title keyword match (confidence 0.9) →
  functional email prefix records@/intake@/liens@/billing@ (0.7) → None.
  Title keyword table mirrors PI_FIRM_PERSONAS.md "Common titles" columns —
  cover all 12 groups' title keywords, not just the 10 keys (map specialized
  titles to the nearest key, e.g. "treatment coordinator"→case_manager,
  "demand writer"→records, "office manager"→coo_ops).
- `map_personas(pif_id=None)` → fill persona/persona_source/
  persona_confidence on firm_contacts where NULL or confidence lower than
  a new source's. Idempotent, never downgrades confidence.
- Design note in docstring: behavioral classification (Front inbox
  attribution) and signature extraction arrive in a later packet and will
  plug in as higher-precedence sources; keep the precedence list a single
  ordered structure.

### 4. CLI (golden rule)
- `research firm <domain-or-pif> [--staff/--no-staff] [--behavior]`
- `research warm --top 50 [--kinds research,staff]`
- `research status [--tasks]` (coverage counts + open tasks)
- `research sync` (poll + upsert without queueing new work)
- `personas map [--pif <id>]`, `personas show <domain>` (contacts with
  persona, source, confidence)
- docs/cli.md §3 rows + §10 recipe ("research the warm list before a
  batch"); update .claude/skills/autocaller/SKILL.md (orchestrator syncs
  the openclaw copy).

### 5. API + UI (small)
- POST /api/research/warm {top_n, kinds}, GET /api/research/status.
- /front: research-coverage chip in the signals panel (researched firms /
  total matched, open tasks); persona shown next to named contacts in
  warm-list expanded rows when present.

### 6. Tests
persona precedence + keyword coverage (incl. specialized-title mapping),
orchestrator budget stop + resume (mock httpx), poll→upsert path (mock),
no-downgrade rule, API smoke. Mock ALL PIF Stats calls in tests.

## Constraints
- PIF Stats is PRODUCTION Precise infrastructure. Hard budget on
  task-creating POSTs (default 30/run), >=2s spacing, never PUT/DELETE,
  never call process-day/generate-outreach/score endpoints.
- During validation: at most 3 real research queues (pick from the top of
  the warm list where research_status is empty) + status polls + 1
  analyze-behavior call. Report task ids and outcomes.
- MC sqlite read-only. NO commits, NO restarts. Don't touch master-agent
  WIP files or frontend/app/ideas/. Don't touch agent_actions/scheduler
  (live sends today: one at 16:30 UTC + a 20-draft batch composing).
- Additive migrations only; no new deps.

## Validation (include output)
- pytest green (new + full suite); npm build passes if frontend touched.
- Real run: `research firm <one un-researched warm domain>` →
  task queued → poll completes → firm_contacts gains titled rows →
  `personas map` assigns personas → `personas show <domain>` prints them.
- `research status` shows sane coverage numbers.

## Done when
The warm list can be researched on demand with budget + resume; completed
research lands as titled contacts; personas auto-assign with source +
confidence; CLI/API/docs/SKILL complete; tests green.
