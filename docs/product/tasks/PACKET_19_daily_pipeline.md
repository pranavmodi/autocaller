# Packet 19 — Daily lead-selection + drafting pipeline (lead-gen daily-run)

You are the implementer in /home/pranav/autocaller. Build the deterministic
daily pipeline that selects ~20 contacts and produces composer drafts as
approval-waiting scheduled actions. It NEVER sends without operator
approval and its daemon loop NEVER starts on daemon boot.

## Read first
- app/services/sequence_recommendations.py (history-aware selection — note
  suppressed_prior_email_contact / suppressed_recent_email_firm and
  EMAIL_FIRM_COOLDOWN_DAYS, just added)
- app/services/lead_gen_email_agent.py (_compose_batch_items / existing
  --batch compose path with only_undrafted_pending)
- app/services/firm_research.py + persona_mapper.py (packet 17)
- app/services/action_execution.py (scheduled actions, 409 guard,
  find_live_scheduled_action_for_item), action_scheduler.py
- app/services/front_sync.py front_sync_loop + _save_front_last_run
  (loop/state patterns), lead_gen_cybernetic.py (policy, observations)
- app/main.py loop startup wiring; CLAUDE.md standing rules (no auto-start)
- The manual batches to mirror: 252d7499... (06-11) and d415c63c... (06-12,
  persona quota mix in reason_json)

## Build

### 1. Schema (alembic, additive)
`lead_gen_daily_runs` (id varchar PK, run_date date UNIQUE, status varchar
[pending|running|partial|completed|failed|skipped], stage varchar,
stages_json jsonb (per-stage outcome: started_at, finished_at, counts,
error), batch_id varchar NULL, created_by varchar, created_at, updated_at).

### 2. `app/services/lead_gen_daily.py`
`run_daily_pipeline(*, dry_run=False, force=False, created_by="daily-run")`
executing stages, checkpointing stages_json after each, resumable:
- **gates**: system_enabled true; active policy daily_send_budget > 0;
  weekday (config); deliverability circuit-breaker: observations last 48h
  with email_send_failed+bounce ratio > policy threshold (default 0.25 of
  sends, min 4 sends) → status=skipped with reason; existing run for
  run_date and not force → return it (if partial, RESUME incomplete stages
  instead of skipping).
- **signals**: front sync last_run age > 30h → run resolve_firms +
  refresh_warm_scores (no API calls); record ages.
- **research**: call packet-17 orchestrate/queue for top
  policy.daily_research_budget (default 10) un-researched warm firms,
  kinds research+behavior; poll bounded (10 min cap) — proceed on timeout,
  research lands for tomorrow. Failures here are non-fatal.
- **personas**: map_personas().
- **select**: selection via recommend_sequence_contacts + persona quota
  from policy (policy json key daily_persona_quota, default {founder_owner:
  5, managing_partner: 4, coo_ops: 3, intake: 3, records: 2, case_manager:
  1, lien_settlement: 1, attorney: 1}), one contact per firm, fill
  shortfall by score order regardless of quota; batch_size from policy
  (default 20). Hard-exclude domains: precisemri.com + any domain of a firm
  with entity_type administrative/medical in mission DB mirror is NOT
  required — but DO exclude contacts whose firm has a suppress flag and the
  Precise domain explicitly.
- **batch**: create lead_gen_batch 'Daily run YYYY-MM-DD' + items with
  persona, warm score, behavior facts (behavioral_json: after_hours_ratio,
  primary_pain_point) and basis in reason_json — mirror batch d415c63c
  shape.
- **compose**: reuse the existing batch-compose path in chunks of 5 with
  per-chunk retry (2 attempts); transient failures leave items undrafted
  and the run status=partial (resume completes them).
- **schedule**: for each drafted item create an action via the existing
  draft→action path in approval-waiting state (NOT approved) with
  scheduled_for spread across policy send window (default 09:00-11:30
  America/Los_Angeles, jittered, same-day if run before window else next
  weekday). Use existing 409 guard; dry_run stops before this stage.
- **notify**: WhatsApp via the openclaw CLI (subprocess `openclaw message
  send --channel whatsapp -t <to> --message ...`, to-number from env
  OPERATOR_WHATSAPP, default +918287149638, prefix '[from cc]'): batch id,
  item/draft counts, persona mix, first 3 subjects, 'review at /lead-gen'.
  Timeout 45s; on timeout verify nothing — just log (delivery
  verification is the orchestrator's job, not the pipeline's).
- Every stage wrapped: exception → stages_json error, status partial/
  failed, later stages skipped, function returns the run record.

### 3. Daemon loop
`daily_run_loop()` checking every 10 min whether (enabled AND now in
window 06:30-08:00 PT AND no completed/running run for today) → run.
Enabled flag persisted in policy/settings storage (NOT env): key
`daily_run_enabled`, default FALSE. Wire into app/main.py startup like
other loops BUT the loop itself no-ops while disabled — the flag survives
restarts and defaults off. NEVER trigger sends; it only creates
approval-waiting actions.

### 4. CLI (golden rule)
`lead-gen daily-run [--dry-run] [--force]` (runs pipeline now, prints
stage table), `lead-gen daily-status [--date YYYY-MM-DD]`,
`lead-gen daily-enable`, `lead-gen daily-disable` (flip the persisted
flag; print loop state). docs/cli.md §3 rows + §10 recipe ("the daily
batch"); update .claude/skills/autocaller/SKILL.md (orchestrator syncs
openclaw copy).

### 5. API + UI (small)
POST /api/lead-gen/daily-run {dry_run, force}, GET /api/lead-gen/daily-runs
?limit=, GET/PUT /api/lead-gen/daily-run/enabled. /lead-gen page: a
"Daily run" card at top showing today's run stage/status/batch link +
enable toggle.

### 6. Tests
Gates (disabled system, budget 0, circuit-breaker math, weekend skip,
idempotency + force, partial resume), quota selection math incl. shortfall
fill + one-per-firm, schedule-time spreading window/jitter/next-weekday,
stage checkpoint/resume on compose failure, notify payload shape (mock
subprocess), API smoke. Mock ALL externals (gateway, PIF, openclaw, DB
sessions where the codebase pattern does).

## Constraints
- NO commits, NO daemon restarts. Do NOT touch master-agent WIP files
  (app/services/master_agent*.py, frontend/app/agents/,
  tests/test_master_agent_runner.py), frontend/app/ideas/, savedresponses/.
- Do NOT modify the scheduler loop or action_execution send gate logic.
- A live batch exists for today (d415c63c..., 20 items, partially drafted)
  and behavior-analysis polling may be running — leave both alone; your
  validation must use dry_run or a synthetic past run_date, never create
  real actions for today.
- The daemon loop default-off rule is non-negotiable (CLAUDE.md: restarts
  must not trigger outbound activity).
- Additive migrations only. No new deps.
- npm build must pass if frontend touched.

## Validation (include output)
- pytest new tests green; full suite not broken; npm build passes.
- `lead-gen daily-run --dry-run` against live data: show the stage table —
  gates pass/skip reasons, selection count + persona mix, NO actions
  created (assert via actions list --scheduled unchanged).
- `lead-gen daily-status` renders.
- Show daily_run_enabled defaults to disabled and survives a flag flip in
  the DB (SQL select), then flip it back to disabled.

## Done when
One CLI command (or the enabled loop, once an operator turns it on)
produces a researched, persona-mixed, history-clean batch of composer
drafts scheduled as approval-waiting actions inside the PT morning window,
with WhatsApp notification, full stage bookkeeping, resume-on-partial, and
the loop off by default; CLI/API/docs/SKILL/tests complete.
