# Packet 18 — pifstats contact intelligence + research-queue isolation (emailtag)

You are the implementer in /home/pranav/emailtag — the email-processing
system running on the CLIENT's (Precise Imaging's) production server. It
powers live email triage and autorespond agents handling ~600 emails/day.
**Nothing you change may alter triage/autorespond behavior or latency.**
Your changes will be reviewed and deployed manually by the operator; you
are editing code only.

Consumer context: /home/pranav/autocaller (Possible OS) orchestrates
research via the pif-info API (see its
docs/product/tasks/PACKET_17_research_orchestrator.md) and maps contacts
to personas per /home/pranav/autocaller/docs/product/PI_FIRM_PERSONAS.md.

## Read first
- app/tasks/worker.py (task_routes — note autorespond runs on 'processing')
- app/tasks/{autorespond,behavior_analysis,firm_research,pif_extraction}.py
- pifstats/src/{email_analyzer,firm_researcher}.py
- app/api/api_v1/endpoints/pif_info.py, app/schemas/pif_info.py,
  app/models/pif_info.py, app/crud/pif_info.py
- docker-compose.yml (worker definitions), alembic/migrations setup

## Build order (isolation FIRST)

### 1. Research-queue isolation (ship-worthy alone)
- Route research/analysis tasks OFF the 'processing' queue to a new
  'research' queue: research_firm_task, research_staff_task,
  analyze_firm_behavior_task, analyze_all_firms_task, score_all_firms_task,
  analyze_leadership_emails_task, and the new tasks below.
  Leave pif_extraction.extract_pif_from_conversation on 'processing' —
  it is part of the live email pipeline.
- docker-compose: add a dedicated worker service for the research queue
  (concurrency 2, modest pids/mem limits, same image/env).
- Celery rate_limit on every research-queue task: '10/m'.
- Support an optional separate OpenAI key: settings.OPENAI_RESEARCH_API_KEY
  falling back to OPENAI_API_KEY; pifstats research/analysis code uses the
  research key. Document in README section.

### 2. Per-contact behavioral profiles (stop discarding sender identity)
In pifstats/src/email_analyzer.py, analyze_firm_emails currently reduces
sender_roles to an anonymous Counter. Extend it to ALSO build
`contact_profiles`: keyed by sender email →
{name, role, message_count, topic_mix, after_hours_ratio, first_seen,
last_seen}. Keep existing outputs unchanged (additive). Persist into the
firm's behavioral_data JSON under 'contact_profiles'. STRICT RULE:
profiles are for FIRM STAFF senders only — patient/personal senders
(consumer email domains: gmail/yahoo/hotmail/outlook/icloud/aol) must be
excluded entirely, and no patient names or case details may appear in any
profile field.

### 3. Persona-aligned role classification
Replace the 4-keyword detect_sender_role with persona classification
aligned to the autocaller taxonomy keys: founder_owner, managing_partner,
coo_ops, intake, records, case_manager, lien_settlement, marketing,
attorney, paralegal, unknown. Implementation: add a 'sender_persona'
output to the EXISTING classify_emails_batch LLM call (same request, one
more field per email; gpt-4o-mini) with a deterministic keyword fallback
when the LLM result is missing. Map old role values for backward compat
(attorney→attorney etc.). sender_roles keeps working (now keyed by the
new taxonomy).

### 4. Signature extraction
New task pifstats/src/signature_extractor.py + Celery task
extract_signatures_task(pif_id) (research queue): for each distinct firm
staff sender in the firm's stored emails, take the 2 most recent message
bodies, one gpt-4o-mini call per sender (batched where easy) extracting
{name, title, direct_phone, persona} from the signature block only.
Persist into behavioral_data.contact_profiles[email]['signature'] =
{title, phone, extracted_at}. Same PHI rule as #2: prompt must instruct
the model to return firm-staff signature data only, never patient
information; add a post-filter dropping any value matching patient-context
patterns (DOB/DOL/MRN/claim numbers).
Wire into analyze-behavior flow: POST /pif-info/{id}/analyze-behavior
gains optional body flag {"signatures": true} to chain it.

### 5. Batch + bulk-poll API (orchestrator efficiency)
- POST /api/v1/pif-info/research/batch {limit<=25, kinds:["research",
  "research_staff","analyze_behavior"], order_by:"icp_score",
  only_unresearched:true} → queues up to limit firms, returns
  [{pif_id, task_ids}] — server-side guard: reject limit>25.
- GET /api/v1/pif-info/research-status?since=<iso>&status=&limit=100 →
  bulk task listing (keep the per-task endpoint).
- Schemas: expose contact_profiles + persona fields in PifInfo response
  schema (additive, optional fields).

### 6. Deprecation marker
generate_outreach_messages + its endpoint: add deprecation docstring +
'X-Deprecated' response header note (outreach now lives in Possible OS).
Do not remove.

## Constraints
- DO NOT modify: app/tasks/email.py task logic, autorespond decision
  logic, tagging/classification rules, inbox routing, bill_offer,
  document/OCR pipeline. The autorespond event recording call stays
  exactly as is.
- All migrations additive (behavioral_data is JSON — likely no migration
  needed; add one only if a real column is required).
- No new pip deps.
- Tests: this repo has a test/ setup — add unit tests for contact_profiles
  building (identity preserved, consumer-domain exclusion), persona
  fallback mapping, signature post-filter (patient-pattern dropped), batch
  endpoint limit guard, and task_routes assertions (autorespond NOT on
  research queue; research tasks NOT on processing). Mock all OpenAI/Front
  calls.
- DO NOT run docker, restart services, or hit production APIs/DB. Code +
  tests only. The operator deploys.
- NO commits.

## Validation (include output)
- pytest for the new/changed modules green; existing tests not broken
  (run what the repo's TESTING.md prescribes, skipping anything that needs
  live services — list what you skipped and why).
- Show a worked example (from a unit-test fixture, not live data) of
  behavioral_data after #2-#4: contact_profiles with persona + signature.
- Diff summary of task_routes before/after.

## Done when
Research load cannot touch autorespond latency (queue + worker + rate
limits); behavior analysis yields per-contact profiles with personas and
signature titles (PHI-excluded by construction); batch/bulk-poll endpoints
exist for the Possible OS orchestrator; deprecation marked; tests green.
