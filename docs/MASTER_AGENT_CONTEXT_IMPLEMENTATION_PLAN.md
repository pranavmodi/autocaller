# Master Agent Context Implementation Plan

This plan implements the context architecture in
`docs/MASTER_AGENT_CONTEXT_ARCHITECTURE.md`.

The goal is not to build a large memory system in one pass. The goal is to
evolve the master agent through small horizontal slices where each slice gives
the agent a clearer way to move the user's goals forward and improve its mental
model of the system.

## Prime Directives

Every implementation slice must serve these two directives:

1. Move fast toward the user's stated short-term and long-term goals,
   effectively and efficiently.
2. Maintain and improve a good mental model of how the system works and how it
   can improve over short and long horizons.

Everything else is subordinate to these objectives.

## Current Baseline

Already exists:

- `soul.md` and `soul.compact.md`;
- master-agent heartbeat;
- durable `master_goals`;
- durable subagent task board;
- durable action execution;
- approved lead-gen email send path;
- product traces;
- action events;
- subagent reports;
- `/agents` UI;
- `/traces` UI;
- lead-gen email-agent slice;
- OpenClaw gateway status-writing call;
- compact recent action summaries in heartbeat context.

Main gaps:

- no first-class `prime_directives` field in wake context;
- no OpenAI prompt-cache-aware split between stable prefix and volatile wake
  state;
- no explicit goal stack by horizon;
- no generic objective-status interpreter;
- no durable way for the agent to ask the user questions;
- no dedicated knowledge base for the agent's system model;
- no retrieval path that loads relevant knowledge pages into heartbeat context;
- no maintenance loop for detecting stale knowledge;
- no UI flow for approving knowledge updates.

## Design Rules

- Build in horizontal slices.
- Keep each slice deployable and inspectable.
- Use Markdown for human-legible knowledge.
- Use database rows for indexing, state, provenance, and UI workflows.
- Do not dump the whole knowledge base into every heartbeat.
- Distinguish raw evidence from curated knowledge.
- Keep `soul.md` protected.
- Keep outbound actions approval-gated unless explicitly allowed.
- Prefer traces, reports, and action results as evidence.
- Add CLI parity for new backend capabilities.
- Update docs and skills when behavior changes.
- Optimize master-agent LLM calls for OpenAI prompt caching by putting stable
  context first and volatile state last.
- Keep the cached prefix deterministic: stable ordering, stable keys, stable
  knowledge summaries, no timestamps or request IDs.
- Log `cached_tokens` when available from OpenAI usage metadata.

## Slice 1: Prompt-Cache-Aware Wake Context V2 Skeleton

### Outcome

Every heartbeat receives a better-structured context packet optimized for
OpenAI prompt caching. The two prime directives appear in the stable prefix, and
volatile wake data appears after the reusable context.

### Build

Add helper functions in `app/services/master_agent.py`:

```python
_prime_directives_context()
_wake_decision_questions()
_stable_operating_doctrine_context()
_stable_output_schema_context()
_stable_capability_definitions(capabilities)
_stable_knowledge_summaries_stub()
_cached_static_context(capabilities)
_goal_stack_context(active_goal, recent_goals)
_system_model_stub()
_current_state_context(...)
_volatile_wake_state(...)
```

Update `_build_wake_context(...)` to emit:

```json
{
  "kind": "master_agent_wake_context_v2",
  "cached_static_context": {
    "prime_directives": [],
    "soul_compact": {},
    "stable_operating_doctrine": {},
    "stable_output_schema": {},
    "stable_capability_definitions": [],
    "stable_knowledge_summaries": [],
    "wake_decision_questions": []
  },
  "volatile_wake_state": {
    "woke_at": "...",
    "actor": "...",
    "goal_stack": {},
    "active_goal": {},
    "current_state": {},
    "recent_evidence": [],
    "capabilities_state": [],
    "current_tasks": [],
    "recent_actions": [],
    "recent_reports": [],
    "recent_events": []
  }
}
```

Keep existing fields for backward compatibility:

- `soul_compact`;
- `active_goal`;
- `configuration`;
- `current_tasks`;
- `recent_actions`;
- `goal_evidence`;
- `recent_reports`;
- `recent_events`;
- `recent_heartbeat_summary`.

Implementation rules:

- Build `cached_static_context` first.
- Do not include timestamps, request IDs, changing status, or recent activity in
  `cached_static_context`.
- Sort capability definitions deterministically by name.
- Split capability definitions from capability state:
  - definition: name, purpose, risk, approval requirement, command shape;
  - state: last status, last verified time, recent failures.
- Use versions or hashes for knowledge summaries instead of dynamic timestamps.
- Preserve the same key order as much as possible.

If the OpenAI/Codex gateway supports passthrough request parameters, add:

```json
{
  "prompt_cache_key": "possible-os-master-agent-v1",
  "prompt_cache_retention": "24h"
}
```

If not supported yet, leave a clear TODO and still keep the prefix stable.

Capture LLM usage metadata if returned:

```json
{
  "cached_tokens": 1234
}
```

Store it under heartbeat `status_llm` metadata.

### UI

Update `/agents` wake context summary to show:

- prime directives;
- short-term goal;
- long-term goal;
- current state;
- known gaps;
- cached token count when available;
- cached static context hash;
- volatile state summary.

### CLI

No new command required.

### Validation

Run:

```bash
python3 -m py_compile app/services/master_agent.py app/api/agents.py app/cli.py
cd frontend && npx tsc --noEmit
.venv/bin/pytest tests/test_master_agent.py -q
```

### Done When

- Heartbeat output shows `kind = master_agent_wake_context_v2`.
- `cached_static_context` exists and appears before `volatile_wake_state`.
- Prime directives are inside the cached static context.
- Volatile fields are not inside the cached static context.
- Stable capability definitions are separated from changing capability state.
- LLM metadata includes cached-token information when returned by the gateway.
- Existing `/agents` UI still loads.
- No behavior regression in sending or task status.

## Slice 2: Objective Status V1

### Outcome

The master agent can see whether the current objective is satisfied,
in-progress, blocked, or stale.

### Build

Add:

```python
_objective_status_context(active_goal, recent_actions, active_tasks, recent_reports)
```

Initial status rules:

- no active goal -> `missing_goal`;
- active manual goal with matching evidence -> `satisfied`;
- active goal with blocking pending question -> `waiting_on_user`;
- active goal with stale task -> `stale`;
- active goal with failed relevant action -> `blocked`;
- otherwise -> `in_progress`.

Replace narrow `_goal_evidence(...)` logic over time, but keep it as an
evidence helper for the first version.

Wake context field:

```json
"objective_status": {
  "active_goal_id": "...",
  "goal": "...",
  "status": "in_progress",
  "evidence": [],
  "remaining_work": [],
  "next_best_action": "..."
}
```

### UI

Add an `Objective status` card in `/agents`:

- status pill;
- evidence list;
- remaining work;
- next best action.

### CLI

Extend:

```bash
bin/autocaller agents status --json
```

No new command unless needed.

### Validation

Run heartbeat with a known completed test-email goal and verify status becomes
`satisfied`.

Run heartbeat with an open manual goal and no evidence and verify status stays
`in_progress`.

### Done When

- The user can inspect the objective status without reading raw JSON.
- The LLM status writer receives `objective_status`.
- The agent no longer relies only on prose from previous heartbeats.

## Slice 3: Ask User Data Model And Backend

### Outcome

The agent can create durable questions for the user.

### Build

Add Alembic migration for:

```text
agent_questions
```

Fields:

```text
id
status
question_type
priority
asked_by
surface
related_goal_id
related_task_id
related_action_id
related_trace_id
question_text
context_json
options_json
recommended_option
blocking
answer_text
answer_json
answered_by
asked_at
answered_at
expires_at
created_at
updated_at
```

Add model row in `app/db/models.py`.

Add service module:

```text
app/services/agent_questions.py
```

Functions:

```python
create_agent_question(...)
answer_agent_question(...)
dismiss_agent_question(...)
list_agent_questions(...)
question_to_dict(...)
```

Behavior:

- If `blocking=true` and `related_task_id` is present, mark the task
  `waiting_on_user`.
- When answered, create `agent_question_answered` trace.
- If the related task was waiting on the user, add task event and optionally
  move it back to `queued`.

### API

Add endpoints under `app/api/agents.py`:

```text
GET  /api/agents/questions
POST /api/agents/questions
POST /api/agents/questions/{id}/answer
POST /api/agents/questions/{id}/dismiss
```

### Validation

Unit tests:

- create question;
- list pending questions;
- answer question;
- blocking question moves task to `waiting_on_user`;
- answer records trace.

### Done When

- The backend can persist and answer questions.
- Related tasks can be blocked by user questions.
- Heartbeat can include pending questions in context.

## Slice 4: Ask User CLI

### Outcome

Operators and agents can manage user questions from the CLI.

### Build

Add commands:

```bash
bin/autocaller agents questions [--status=pending --json]
bin/autocaller agents ask-user "..." \
  --type=clarification \
  --priority=normal \
  --surface=agents \
  --blocking \
  --goal=<goal_id> \
  --task=<task_id>
bin/autocaller agents answer-question <id> --answer "..."
bin/autocaller agents dismiss-question <id>
```

### Validation

Run:

```bash
bin/autocaller agents ask-user "Confirm test question" --json
bin/autocaller agents questions --json
bin/autocaller agents answer-question <id> --answer "confirmed" --json
```

### Done When

- CLI covers create/list/answer/dismiss.
- Output is useful in both table and JSON modes.

## Slice 5: Questions UI

### Outcome

The user can see and answer agent questions in `/agents`.

### Build

Add `Questions for Pranav` section.

Show:

- question text;
- type;
- priority;
- blocking status;
- related goal/task/action links;
- recommendation;
- context summary;
- answer text area;
- answer button;
- dismiss button.

For real-world actions, show:

- requested action;
- why it is needed;
- step-by-step instructions from `context_json`;
- evidence input;
- `I did this` button.

### Validation

Manual:

- create question from CLI;
- see it in UI;
- answer it in UI;
- verify it disappears or moves to answered.

Automated:

```bash
cd frontend && npx tsc --noEmit
cd frontend && npm run build
```

### Done When

- User questions are visible without raw JSON.
- The user can answer a question from the browser.
- Blocking questions are visually distinct.

## Slice 6: Questions In Wake Context

### Outcome

Every heartbeat sees pending questions and understands whether they block the
current objective.

### Build

Add:

```python
_open_questions_context(active_goal, limit=10)
```

Wake context:

```json
"open_questions": [
  {
    "id": "...",
    "question_type": "approval",
    "question_text": "...",
    "blocking": true,
    "related_goal_id": "..."
  }
]
```

Update objective status:

- if a blocking pending question relates to current goal -> `waiting_on_user`.

Update master status skill:

- if waiting on user, say what is needed in plain language.

### Validation

Create a blocking question linked to an active goal, run heartbeat, verify:

- wake context includes question;
- objective status is `waiting_on_user`;
- human status says what is needed.

### Done When

- The agent can pause safely instead of guessing.
- Open questions survive across heartbeat runs.

## Slice 7: Knowledge Base File Skeleton

### Outcome

The knowledge base exists as human-readable Markdown files.

### Build

Create:

```text
docs/agent-kb/
  README.md
  system-model/
    possible-os.md
    lead-gen-loop.md
    action-execution.md
    email-sending.md
    tracing-and-learning.md
    master-agent-heartbeat.md
    subagents.md
  goals/
    current-goal-stack.md
    long-term-roadmap.md
  decisions/
    README.md
  runbooks/
    send-approved-lead-gen-emails.md
    inspect-heartbeat.md
    recover-email-send-failure.md
  open-questions/
    README.md
  glossaries/
    possible-os-terms.md
```

Each page should include frontmatter:

```yaml
---
slug: lead-gen-loop
kind: system_model
title: Lead Gen Loop
confidence: medium
review_status: draft
updated_by: operator
---
```

### Validation

No code validation needed beyond checking files exist.

### Done When

- A human can read the current system model in docs.
- The master-agent mental model is no longer only in code or traces.

## Slice 8: Knowledge Base DB Index

### Outcome

Markdown knowledge pages are indexed in the database for listing, search, and
wake-context selection.

### Build

Add Alembic migration:

```text
agent_knowledge_pages
```

Fields:

```text
id
slug
title
kind
path
summary
content_md
tags_json
links_json
source_trace_ids_json
source_action_ids_json
source_report_ids_json
source_urls_json
confidence
review_status
owner
version
supersedes_id
created_by
updated_by
created_at
updated_at
reviewed_at
```

Add service:

```text
app/services/agent_knowledge.py
```

Functions:

```python
sync_knowledge_pages_from_disk()
list_knowledge_pages(...)
get_knowledge_page(slug)
search_knowledge_pages(query)
knowledge_page_to_dict(row)
```

Use simple text matching first. Add embeddings later only if useful.

### API

```text
GET  /api/agents/knowledge
GET  /api/agents/knowledge/{slug}
POST /api/agents/knowledge/sync
```

### CLI

```bash
bin/autocaller agents knowledge sync
bin/autocaller agents knowledge list
bin/autocaller agents knowledge show <slug>
bin/autocaller agents knowledge search <query>
```

### Validation

Tests:

- sync reads Markdown pages;
- frontmatter is parsed;
- pages can be listed and fetched;
- search returns relevant pages.

### Done When

- Knowledge pages are queryable through API and CLI.
- The DB index can be rebuilt from files.

## Slice 9: Knowledge In Wake Context

### Outcome

Heartbeat receives a compact knowledge bundle.

### Build

Add:

```python
_knowledge_context(active_goal, recent_actions, current_tasks)
```

Initial simple rule:

- always include summaries for:
  - `possible-os`;
  - `master-agent-heartbeat`;
  - active workflow page if detectable, e.g. `lead-gen-loop`;
- include stale pages list if `review_status=stale`.

Wake context:

```json
"knowledge_context": {
  "loaded_pages": [],
  "system_model_summary": {},
  "known_gaps": [],
  "stale_pages": []
}
```

### UI

In `/agents`, show:

- loaded knowledge pages;
- stale pages;
- link to page detail.

### Validation

Run heartbeat and verify loaded pages appear in input JSON and UI.

### Done When

- The agent has a compact mental model at wake.
- It does not need to read all docs every time.

## Slice 10: Knowledge UI

### Outcome

The user can inspect the master agent's mental model from the app.

### Build

Add `/knowledge` or a tab inside `/agents`.

Views:

- list pages by kind/status;
- search pages;
- show Markdown content;
- show provenance fields;
- show stale/draft/reviewed status.

First version can be read-only.

### Validation

Frontend build and manual route smoke check.

### Done When

- The system model is visible in the app.
- Knowledge is not hidden in Markdown files only.

## Slice 11: Proposed Knowledge Updates

### Outcome

The agent can propose updates to its mental model without applying them
silently.

### Build

Option A: add table:

```text
agent_knowledge_update_proposals
```

Fields:

```text
id
status                 proposed | accepted | rejected | applied
page_slug
proposal_type          append | replace_section | mark_stale | create_page
summary
rationale
evidence_json
patch_md
created_by
reviewed_by
created_at
reviewed_at
applied_at
```

Option B: reuse `improvement_findings` with a `target = knowledge_base`.

Recommendation:

Use a separate table if knowledge updates become a first-class product surface.
Use `improvement_findings` for the first minimal version if speed matters.

### UI

Show proposals in `/agents` or `/knowledge`:

- proposed change;
- rationale;
- evidence;
- accept/reject buttons.

### Validation

Create a fake proposal, accept it, verify the page updates or accepted status is
recorded.

### Done When

- The agent can identify stale knowledge without silently rewriting docs.

## Slice 12: Apply Knowledge Updates

### Outcome

Accepted knowledge updates can patch Markdown and resync the DB.

### Build

Add service:

```python
apply_knowledge_update_proposal(proposal_id)
```

Rules:

- only accepted proposals can apply;
- write Markdown with safe scoped replacement;
- preserve frontmatter;
- resync page row;
- record `agent_knowledge_updated` trace;
- do not modify `soul.md`.

### Validation

Tests:

- append section;
- replace section;
- create page;
- reject unsafe path.

### Done When

- The KB can evolve with approval.
- Updates are traceable.

## Slice 13: System Model Drift Detector

### Outcome

Heartbeat can notice when recent evidence contradicts current knowledge.

### Build

Deterministic V1 rules:

- If a send path records transport not mentioned in `email-sending.md`, propose
  KB update.
- If a repeated action failure appears and no runbook exists, propose runbook.
- If a new capability exists but no KB page mentions it, propose update.
- If user answers a durable question with architecture info, propose KB update.

Later:

- add LLM-assisted comparison using OpenClaw gateway.

### Validation

Seed evidence that should trigger a proposal, run heartbeat/analyze command,
verify proposal created.

### Done When

- The master agent can maintain its mental model, not just read it.

## Slice 14: Ask User From Agent Decisions

### Outcome

The master agent can decide to ask a question as part of heartbeat when it lacks
information or approval.

### Build

Add conservative deterministic triggers first:

- objective status blocked because missing approval -> ask approval question;
- missing credential/config detected -> ask real-world action question;
- active goal has two conflicting next actions -> ask strategic decision;
- repeated failed action with unknown cause -> ask clarification or real-world
  check.

Do not let the LLM create arbitrary questions directly at first.

Pipeline:

```text
heartbeat context
-> deterministic question detector
-> create agent_question if no duplicate pending question exists
-> include it in heartbeat output
```

### Validation

Simulate missing config and verify one pending question is created, not repeated
every heartbeat.

### Done When

- The agent can ask for help only when needed.
- Duplicate spam is prevented.

## Slice 15: Human-In-The-Loop Action Integration

### Outcome

Questions and approvals become one coherent interruption system.

### Build

Link:

- `agent_questions`;
- `agent_actions`;
- `operator_notifications`;
- `agent_tasks`.

Pattern:

- action requires approval -> create action + question/notification;
- user approves -> answer question + approve action;
- heartbeat can execute approved action if allowed;
- result links back to action/question/goal.

### Validation

End-to-end:

1. Agent proposes a real lead-gen send.
2. User approves.
3. Heartbeat sends.
4. Action result links to email log.
5. Objective status advances.

### Done When

- The user sees pending decisions in one place.
- The agent can resume after user input.

## Slice 16: Documentation And Skill Sync

### Outcome

The new context, question, and KB systems become part of the operating
procedure.

### Build

Update:

- `docs/MASTER_AGENT_CONTEXT_ARCHITECTURE.md`;
- `docs/MASTER_AGENT_CONTEXT_IMPLEMENTATION_PLAN.md`;
- `docs/MASTER_AGENT_LEARNING_SYSTEM.md`;
- `docs/ACTION_EXECUTION_ARCHITECTURE.md`;
- `docs/cli.md`;
- `.claude/skills/autocaller/SKILL.md`;
- `/root/.openclaw/workspace/skills/autocaller/SKILL.md`.

### Validation

Run:

```bash
git diff --check
```

### Done When

- Future agents know how to operate and extend the system.

## Recommended First Implementation Batch

Do these first:

1. Slice 1: Wake Context V2 Skeleton.
2. Slice 2: Objective Status V1.
3. Slice 3: Ask User Data Model And Backend.
4. Slice 4: Ask User CLI.
5. Slice 5: Questions UI.
6. Slice 6: Questions In Wake Context.

Why:

- They directly improve the master agent's ability to move toward user goals.
- They let the agent stop safely when it needs the user.
- They make objective status explicit.
- They do not require the full knowledge base yet.

Then:

1. Slice 7: Knowledge Base File Skeleton.
2. Slice 8: Knowledge Base DB Index.
3. Slice 9: Knowledge In Wake Context.
4. Slice 10: Knowledge UI.

Why:

- This creates the durable mental model.
- The files stay human-legible.
- The DB enables retrieval and UI.

Finally:

1. Slice 11: Proposed Knowledge Updates.
2. Slice 12: Apply Knowledge Updates.
3. Slice 13: System Model Drift Detector.
4. Slice 14: Ask User From Agent Decisions.
5. Slice 15: Human-In-The-Loop Action Integration.
6. Slice 16: Documentation And Skill Sync.

Why:

- This turns memory into a self-improving loop.
- It should come after the basics are visible and reliable.

## Acceptance Criteria For The Whole Plan

The plan is complete when:

- every heartbeat starts with the two prime directives;
- every heartbeat includes a goal stack;
- every heartbeat includes objective status;
- the agent can create durable questions for the user;
- the user can answer questions from `/agents`;
- blocking questions pause related tasks;
- answers are included in future wake contexts;
- the system model exists as Markdown knowledge pages;
- knowledge pages are indexed in DB;
- heartbeat loads relevant knowledge summaries;
- the user can inspect knowledge pages in the UI;
- the agent can propose knowledge updates from evidence;
- approved knowledge updates are traceable and reversible;
- the system can distinguish raw events, interpreted objective status, and
  durable knowledge.

## Stop Conditions

Pause and ask the user before:

- changing `soul.md`;
- auto-applying knowledge changes without review;
- adding vector/embedding infrastructure;
- allowing LLM-generated questions to create user notifications without
  deterministic guardrails;
- allowing the agent to execute new external actions beyond already-approved
  paths;
- making schema changes that risk existing data without a migration/backfill
  check.
