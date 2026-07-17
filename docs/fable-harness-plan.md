# Fable Harness Plan — Memory, Workflows, Context Management, and a Self-Learning Harness for the Master Agent

Date: 2026-07-12
Sources: current implementation (`app/services/master_agent.py`,
`app/services/master_agent_runner.py`, `app/services/product_learning.py`,
`app/skills/master-agent-{status,runner}/SKILL.md`),
`docs/MASTER_AGENT_LEARNING_SYSTEM.md`,
`docs/MASTER_AGENT_CONTEXT_ARCHITECTURE.md`, and Lilian Weng,
"Harness Engineering for Self-Improvement" (2026-07-04,
https://lilianweng.github.io/posts/2026-07-04-harness/).

---

## 1. How the master agent works today (grounded in code)

What actually runs, as opposed to what the design docs describe:

**Heartbeat loop** (`run_master_heartbeat`, `master_heartbeat_loop`, default
300s). Each wake builds a v2 wake context with two blocks:

- `cached_static_context` — prime directives, `soul.compact.md`, stable
  operating doctrine, stable output schema, stable capability definitions,
  wake decision questions, and **`_stable_knowledge_summaries_stub()` — a
  stub**. Deterministically ordered for prompt-cache prefix stability; cache
  telemetry (`cached_tokens`) is recorded.
- `volatile_wake_state` — goal stack, `objective_status` (interpreted goal
  evidence), current operating state, recent evidence (durable action
  snapshots with email-log proof), capabilities state, queue-age analysis,
  compressed prior-heartbeat summary, tasks/reports/events.

The status call goes through the OpenClaw gateway with
`master-agent-status/SKILL.md`; a deterministic fallback keeps the heartbeat
alive on gateway failure and records which path wrote the status.

**Bounded tool runner** (`master_agent_runner.py`, flag-gated, max 5
iterations / 90s / 50KB per call). The LLM picks one structured decision per
iteration from three tools: `filesystem_read` (read-only repo inspection),
`action_read` (durable action outcome inspection — the cybernetic error
signal), and `sandbox_write` (scoped to `data/agent-sandbox/`). Every
iteration is a `product_traces` row with its own `trace_id`. Continuation
state (`files_read`, `facts_learned`, `remaining_questions`,
`next_suggested_tool_call`) persists in `agent_reports` rows and is merged
across runs so weak heartbeats don't erase progress.

**Goals.** `synthesize_master_goal` is deterministic (stale queue → missing
runners → SystemsHealth → findings → discovery). Manual goals via
`bin/possibleos agents set-goal` override until expiry. No `master_plans` /
`master_plan_items` yet.

**Subagents.** Task board exists (`agent_tasks`, `agent_task_events`,
`agent_reports`, `agent_capabilities`). Two hardcoded workers:
ResearchScoutAgent (deterministic RSS fetch → learning note, one note ever
written) and SystemsHealthAgent (read-only service/journal/health checks →
report). No LLM inside either worker; no generic worker runtime.

**Learning loop** (`product_learning.py`). `sync_outcome_traces` +
`analyze_recent_activity` use **deterministic heuristics** (e.g.
`_contains_precise`) to draft `improvement_findings`; Pranav reviews;
accepted findings can generate `eval_cases` and Codex task packets
(markdown under `data/codex_tasks/`). **Nothing executes eval cases** —
there is no eval runner, so "eval-backed change" is aspirational.

**What exists nowhere yet:** `docs/agent-kb/` knowledge base (the wake
context ships a stub), layered memory files (`memory/YYYY-MM-DD.md`,
`MEMORY.md`), `agent_questions` (ask-user capability), skillification,
post-change measurement, and any loop that edits the harness itself. The
only durable "mental model" artifact is one sandbox file,
`data/agent-sandbox/master-agent-understanding.md`.

**One-line diagnosis:** the *acting* skeleton (heartbeat → context → bounded
tools → traces → reports) is real and safe; the *learning* half (memory that
compounds, evals that run, changes that are proposed/validated/measured) is
designed on paper but not closed anywhere.

---

## 2. What the Weng article adds

The article's thesis: near-term recursive self-improvement happens in the
**harness** — the layer that decides how the model thinks, plans, calls
tools, manages context, stores artifacts, and evaluates results — not in the
weights. The ideas we adopt, mapped to this repo:

1. **Context as an evolving playbook, not a lengthening prompt (ACE).**
   Generator (task trajectories) → Reflector (distill lessons from
   success/failure) → Curator (update itemized context entries with
   helpful/harmful counters, merge/dedup). We already have the Generator
   (heartbeat + runner traces). We have no Reflector or Curator.
2. **File system as persistent memory.** Durable state in human-legible
   files, DB-indexed for search — exactly the Markdown-first `agent-kb`
   design already specced. LLMs are natively file-system literate; the
   runner already proves this with sandbox notes.
3. **Sub-agent parallelism must be explicit and inspectable** — persistent
   logs and reports, never transient context. The task board already does
   this; keep it as the only delegation path.
4. **Self-Harness loop:** mine failures into verifier-grounded patterns →
   propose *bounded* harness edits → validate against held-in evals (does it
   fix the weakness?) and held-out evals (does it break anything?). This is
   the concrete recipe for our findings→change pipeline.
5. **Evaluator and permission control sit outside the loop.** The thing
   being improved must never grade itself or approve its own changes.
   Held-out tests, trace audits, human review.
6. **Preserve negative results.** Failed proposals and failed heartbeat
   strategies are training signal; make them durable, not just log noise.
7. **Optimization progression:** prompts → structured context → workflows →
   harness code. Climb this ladder in order; don't let the agent edit
   harness *code* before it can competently edit its own *context*.
8. **Humans move up the stack, not out.** Pranav's role shifts from
   reviewing drafts to reviewing findings, eval definitions, and harness
   diffs.

---

## 3. Gap analysis (current → target)

| Layer | Today | Target |
|---|---|---|
| Constitutional memory | `soul.md` / `soul.compact.md`, protected | unchanged (never in the optimization surface) |
| Goal memory | `master_goals`, deterministic synthesizer | + `master_plans`/`master_plan_items`, LLM synthesizer *behind evals* |
| System-model memory | one sandbox file, stub in wake context | `docs/agent-kb/` Markdown + `agent_knowledge_pages` index, loaded into wake context |
| Episodic memory | traces/events/reports/actions (good) | + daily `memory/YYYY-MM-DD.md` digest; unchanged otherwise |
| Procedural memory | 2 static SKILL.md files | + runbooks in KB; skillification loop proposes new ones |
| Playbook / lessons | none | `agent_context_items` (ACE-style itemized entries) |
| Context mgmt | v2 builder, cache-aware, stub knowledge | v3 builder: KB summaries + playbook items, budgets, relevance selection |
| Workflows | 2 hardcoded workers | declarative workflow packets run by one generic worker runtime |
| Evals | cases created, never run | `eval_runner` + `eval_runs`, held-in/held-out split |
| Self-learning | heuristic findings, human review, dead-ends after acceptance | full propose→validate→approve→apply→measure loop over bounded surfaces |
| Negative results | discarded | `harness_experiments` ledger (incl. rejected/failed) |
| Ask-user | designed only | `agent_questions` (kept from existing plan; prerequisite for safe autonomy) |

---

## 4. The plan — four workstreams, built as thin complete loops

House rule applies throughout: every slice ships backend + CLI +
`docs/cli.md` + SKILL.md sync, gateway calls target `openclaw/proxy`, and
prompt/skill changes follow the prompt-change protocol (version bump,
commit, push, restart). Every new mutation surface gets an explicit flag and
trace events.

### Workstream A — Memory (knowledge base + reflection)

**A1. Knowledge base v1 (Markdown-first, DB-indexed).**
- Create `docs/agent-kb/` with seed pages written by hand or promoted from
  the existing sandbox understanding file:
  `system-model/master-agent-heartbeat.md`, `system-model/tool-runner.md`,
  `system-model/lead-gen-loop.md`, `system-model/action-execution.md`,
  `goals/current-goal-stack.md`, `runbooks/inspect-heartbeat.md`.
- Alembic migration: `agent_knowledge_pages` (slug, title, kind, path,
  summary, content_md, tags, source ids, confidence, review_status,
  version, supersedes_id — per the architecture doc).
- Sync service `app/services/knowledge_base.py`: Markdown ⇄ DB, hash-based
  staleness detection.
- CLI: `bin/possibleos kb list|read|search|sync`.

**A2. Wire KB into the wake context.** Replace
`_stable_knowledge_summaries_stub()` with a real loader: top-N page
summaries selected by tag-match against the active goal, sorted by slug,
carrying `version` hashes (never timestamps) so the cached prefix stays
byte-stable between KB edits. Full page content is *not* inlined; the
runner gets a `kb_read` tool (thin wrapper over `filesystem_read` scoped to
`docs/agent-kb/`) for on-demand expansion. This is progressive disclosure
done properly.

**A3. Reflector (closes the memory loop).** A daily job (heartbeat-triggered,
like the existing daily cadence design) that:
- reads the last 24h of runner continuation reports, heartbeat outcomes,
  blocked/failed actions, and finding drafts;
- calls `openclaw/proxy` with a new `master-agent-reflector` SKILL.md to
  produce: (a) proposed KB page updates/creations as diffs, (b) proposed
  playbook items (see B2), (c) a daily digest written to
  `memory/YYYY-MM-DD.md`;
- writes proposals to a review queue (reuse `improvement_findings` with
  `finding_type=knowledge_update`), **never patches KB pages directly**.
- Approval via `/agents` UI + `bin/possibleos kb approve <id>` applies the
  patch, bumps page version, syncs DB, traces the update.
- Update rules from the architecture doc apply: user-stated facts write
  immediately (operator-invoked), inferred lessons always propose-for-review,
  one-off noise never promotes.

**A4. Ask-user capability** (`agent_questions` table, API, CLI,
`/agents` "Questions for Pranav" section, `open_questions` in wake context,
blocking questions set tasks to `waiting_on_user`). Unchanged from the
existing implementation plan — pulled forward because both the Reflector
and the self-learning loop need a durable escalation channel. Durable
answers feed A3 as immediate-write knowledge.

### Workstream B — Context management (ACE-style)

**B1. Context builder v3 as a versioned, testable module.** Extract wake
context assembly from `master_agent.py` (~40 `_*_context` functions) into
`app/services/wake_context.py` with an explicit `context_version` field and
golden-file tests asserting (a) section ordering, (b) byte-stability of the
cached prefix across two builds with identical inputs, (c) token-budget
compliance per section. This makes context a *harness surface the learning
loop can later edit safely* — you can't optimize what you can't regression-test.

**B2. Playbook items (the ACE curator's substrate).** New table
`agent_context_items`: id, text (one imperative lesson, e.g. "If an action
is blocked as a duplicate, do not retry; propose cleanup"), tags,
helpful_count, harmful_count, status, source_finding_id. A bounded set
(budget: ~15 items / ~1,200 tokens) is rendered into the *durable memory*
block of the wake context, between stable prefix and volatile state, sorted
by id for cache friendliness. The Reflector proposes items; the status
skill is amended to cite item ids it relied on; citations increment
helpful/harmful counters from outcome evidence; the curator step
merges/dedups and retires net-harmful items (grow-and-refine, no context
collapse from monolithic rewrites).
- CLI: `bin/possibleos playbook list|add|retire|stats`.

**B3. Budgets and compaction.** Per-section token budgets in agent config
(exposed in `/api/agents/config` + CLI like existing runner config); the
builder truncates volatile lists (evidence, events) against budget with
`truncated=true` markers; continuation-state compaction already exists —
extend the same compactor to KB summaries and playbook rendering. Log
`cached_tokens` ratio per heartbeat into status metadata (plumbing exists)
and surface it on the `/agents` dashboard so B-workstream changes are
measurable.

### Workstream C — Workflows

**C1. Declarative workflow packets.** Generalize the two hardcoded workers
into data: `agent_workflows` table (or `app/workflows/*.yaml`, DB-indexed
like the KB) defining: objective template, allowed tools, forbidden
actions, output schema, acceptance criteria, verification commands, risk
level, `requires_human_approval`. `run_research_scout_task` and
`run_systems_health_task` become the first two packets executed by one
generic `run_workflow_task(task_id)` runtime that reuses the bounded runner
(same iteration/runtime/output caps, same per-iteration tracing). The master
delegates by instantiating a packet, exactly matching the delegation-packet
schema already in `MASTER_AGENT_LEARNING_SYSTEM.md`.
- CLI: `bin/possibleos workflows list|show|run|validate`.

**C2. Skillification loop.** Weekly Reflector pass over runner traces: if
the same tool-call sequence (normalized: tool+operation+path-prefix)
appears ≥3 times across heartbeats, propose a runbook page in
`docs/agent-kb/runbooks/` (via A3's review queue). Runbooks that mature get
promoted by hand into SKILL.md files or workflow packets. This is the
existing "skillification rule" made mechanical.

**C3. Plans.** Add `master_plans` / `master_plan_items` (schema already
specced). The deterministic goal synthesizer gains one new top-priority
input: the highest-priority `in_progress` plan item. Heartbeat reports plan
progress in `objective_status`. Chat/CLI steering
(`bin/possibleos plans add|list|reprioritize`) satisfies the "parallel
short-term and long-term loops" requirement without an LLM planner yet —
the LLM planner waits until D1 gives us evals to gate it with.

### Workstream D — Self-learning harness

**D1. Eval runner (the keystone — nothing above it is safe without it).**
- `app/services/eval_runner.py` + `eval_runs` table (eval_case_id, target
  surface + version, input snapshot, output, grade, grader, duration,
  created_at).
- Executes an `eval_cases` row against a target surface: render the
  surface's prompt (status skill, runner skill, composer skill, context
  builder version) with the case's input snapshot, call `openclaw/proxy`,
  grade with a deterministic checker where possible (JSON-schema
  conformance, required/forbidden strings, decision-type match) and an LLM
  judge (separate model, per "evaluator outside the loop") otherwise.
- Seed suite (~15 cases, mostly from real traces): the three example evals
  in the learning-system doc (composer, delegation, heartbeat triage) plus
  runner-decision cases mined from `master_agent_runner_iteration` traces
  (given this wake context + observations, decision must be X-type).
- Tag every case `held_in` (derived from a finding being fixed) or
  `held_out` (regression; never shown to any proposing loop).
- CLI: `bin/possibleos evals list|run|run-suite|results`.

**D2. Failure mining upgrade.** Extend `analyze_recent_activity` beyond
`_contains_precise`-style heuristics: batch recent failure evidence
(heartbeat fallback statuses, runner `blocked` decisions, policy-blocked
actions, stale tasks, user edits/rejections/regenerations, market outcomes)
through an `openclaw/proxy` classifier skill that groups them into findings
with `evidence_trace_ids`, severity, confidence, and — new —
`suspected_harness_surface` (which skill/context section/workflow packet the
failure implicates). Deterministic heuristics stay as pre-filters (per the
LLM-first standing rule).

**D3. The self-harness loop (propose → validate → approve → apply → measure).**
For an accepted finding whose surface is *bounded* — allowed surfaces in
strict order of trust: (1) playbook items, (2) KB pages, (3) SKILL.md files,
(4) workflow packet definitions, and **only later** (5) context-builder
config. `soul.md`, policy gates, eval definitions, the eval runner, and
approval code are permanently out of surface:

1. **Propose:** a bounded runner task drafts the edit (diff) with rationale
   citing evidence traces. For playbook/KB surfaces this is the Reflector
   path (A3/B2); for SKILL.md diffs generate 2–3 distinct variants
   (diversity guard against single-solution collapse).
2. **Validate:** eval runner executes held-in cases (must improve) and the
   held-out suite (must not regress) per variant; results attach to the
   proposal.
3. **Approve:** human gate in `/agents` + `bin/possibleos harness
   proposals|approve|reject`, showing diff, eval delta, and evidence.
   No auto-apply in v1 for any surface above playbook items.
4. **Apply:** SKILL.md changes go through the prompt-change protocol
   (version bump, commit, push, restart — already a standing rule);
   playbook/KB apply via A3/B2 mechanics. Every application emits
   `harness_change_applied` traces.
5. **Measure:** `harness_experiments` table (proposal, surface, variants,
   eval deltas, applied_at, 7/30-day before/after metrics, status —
   *including rejected and failed rows*: the negative-results ledger).
   Weekly heartbeat pass compares before/after on the metric the finding
   targeted and writes the outcome back onto the experiment row and, via
   the Reflector, into the KB.

**D4. Guardrails (non-negotiable, mostly restating + extending existing rules).**
- Evaluator, held-out cases, and approval gates live outside every
  optimization surface; the proposer never sees held-out case content.
- One harness change in flight per surface at a time; every change has a
  one-command rollback (git revert + restart for skills; status flip for
  playbook items).
- Reward-hacking audit: the weekly measure pass checks proxy metrics
  against user-judgment signals (edit/rejection rates) — a change that
  improves eval pass-rate but raises user corrections is auto-flagged for
  reversal.
- All existing constraints stand: no `soul.md` edits, no subagent
  self-acceptance, no auto-send outside approval policy, no restarts while
  a call is active.

---

## 5. Build sequence

Each slice is a complete loop (input → decision → action → feedback →
inspectable dashboard/CLI), ordered so every slice makes the next one safer:

| # | Slice | Workstream | Why this order |
|---|---|---|---|
| 1 | KB v1 + wake-context wiring (A1, A2) | Memory | Replaces the stub; immediate context quality win; zero new mutation risk (read-only + operator-synced) |
| 2 | Eval runner + seed suite (D1) | Learning | The verifier must exist before any loop writes anything; also immediately useful for manually testing skill edits |
| 3 | Reflector + daily digest + KB review queue (A3) | Memory | First automated write path, fully human-gated; starts compounding memory |
| 4 | Playbook items + context builder v3 + golden tests (B1, B2, B3) | Context | ACE loop closes: generator→reflector→curator all live; measurable via cache + fallback metrics |
| 5 | Ask-user capability (A4) | Memory/HITL | Unblocks higher autonomy; Reflector and self-harness escalations need it |
| 6 | Self-harness on playbook + SKILL.md surfaces (D2, D3, D4) | Learning | Narrowest useful self-improvement loop, eval-gated and human-approved |
| 7 | Workflow packets + generic worker runtime (C1) | Workflows | Delegation becomes data; new subagents stop requiring code |
| 8 | Skillification + plans (C2, C3) | Workflows | Needs traces from 4–7 to have anything worth skillifying |
| 9 | LLM goal synthesizer + workflow-definition surface in self-harness | stretch | Only after 1–8 provide evals, guardrails, and measurement |

Rough sizing: slices 1–3 are each a few bounded days; 4 and 6 are the
biggest (a week-ish each); 5, 7, 8 are moderate. Each slice ends with:
CLI + `docs/cli.md` + SKILL.md sync, decision-log entry, and an
implementation note appended to this file and the two master-agent docs
(per the architecture/plan sync rule).

---

## 6. Metrics — how we know the harness is actually learning

Instrument from slice 1; show on the `/agents` learning dashboard:

- **Context health:** `cached_tokens` ratio per heartbeat; LLM-status vs
  fallback rate; wake-context token size by section.
- **Memory compounding:** KB pages by review_status; stale-page count;
  proposed→approved knowledge-update rate; repeat-inspection rate (runner
  re-reading files already in continuation state should *fall*).
- **Playbook quality:** items by status; helpful/harmful ratios; citation
  rate in status outputs.
- **Learning throughput:** findings by source-signal type; finding→eval→
  applied-change conversion; eval pass-rate trend on held-out suite
  (must be monotone-ish; a drop is an incident).
- **Outcome truth:** goal `objective_status` satisfaction rate; stale-task
  rate; user edit/rejection rates on drafts; per-experiment before/after
  deltas from `harness_experiments`, including the count of *negative
  results preserved* (if this is zero, the loop is lying to us).
