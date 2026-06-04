# Possible OS Master Agent Learning System

Last updated: 2026-06-03

## Purpose

Possible OS should become the operating system for Possible Minds.

It should not only wait for Pranav to ask for work. It should proactively run
the company through an OODA loop:

1. Observe what is happening across products, inboxes, traces, customers,
   outreach, SEO, code, docs, system health, and the web.
2. Orient around the current situation using `soul.md`, memory, metrics, and
   recent user judgment.
3. Decide the next highest-leverage actions.
4. Act through tools, workflows, and subagents.
5. Measure results.
6. Learn from user corrections and real-world feedback.
7. Improve skills, prompts, policies, workflows, UI, code, and docs.

The system is inspired by cybernetics, systems thinking, complexity, OODA,
operator-led companies, and self-improving agent loops.

The protected source of identity is `soul.md`. The master agent may read it and
propose changes, but may not edit it unless Pranav explicitly asks. Everything
else can be improved if evidence, evaluation, and risk gates support it.

## Design Principle

The master agent should behave like a founder-operator with a nervous system:

- curious enough to discover new information;
- muscular enough to act;
- reflective enough to learn;
- disciplined enough to measure;
- humble enough to ask for review when consequences are high.

It should be Esalen, not Foxconn: alive, reflective, creative, learning-oriented,
and human-centered, while still capable of operational rigor.

It should build in horizontal slices. Do not design or implement a giant
multi-month capability in one jump. Build the smallest complete loop that works
end to end, then evolve it. The guiding quote:

> A complex system that works is invariably found to have evolved from a simple
> system that worked.

For Possible OS, this means every major capability should start as a thin
working loop:

- one observable input;
- one decision path;
- one action;
- one feedback signal;
- one learning/update path;
- one dashboard or report that makes the loop inspectable.

Then add breadth, nuance, autonomy, and optimization only after the simple loop
has proven that it works.

It should be prompt-cache aware. Large language model calls should be organized
so stable context appears first and changes as little as possible across runs.
This reduces cost/latency where the provider supports prompt caching and also
makes the system easier to reason about.

For master-agent and subagent calls, structure context in this order:

1. stable identity and operating principles;
2. stable skill or role instructions;
3. stable schemas, output contracts, and safety boundaries;
4. slowly changing project docs or policy summaries;
5. compact memory summaries and pointers;
6. current task packet;
7. fresh observations, traces, logs, emails, or user messages.

Do not place volatile timestamps, random IDs, raw logs, large trace blobs, or
one-off observations before stable instructions. Put volatile material near the
end of the prompt or pass it as a separate current-input payload. When creating
subagent task packets, keep the shared prefix stable across similar tasks and
vary only the final task-specific section.

Prompt-cache awareness is not a reason to overstuff prompts. It works together
with progressive disclosure: keep the stable prefix lean, point to large docs,
and expand only the references needed for the current decision.

It should also use progressive disclosure. LLMs have limited context windows, so
the system should not stuff every document, trace, and policy into every prompt.
Instead:

- load full `soul.md` as protected constitutional context only when the master
  agent is making strategic or self-improvement decisions;
- pass `soul.compact.md` as compact constitutional guidance for frequent
  heartbeat/status calls;
- pass full `soul.md` hashes and pointers by default so changes are detectable
  without stuffing the full protected document into every prompt;
- expand into detailed docs, traces, or artifacts only when the current decision
  needs them;
- keep `SKILL.md` files lean and procedural;
- move long references into linked docs or `references/` files;
- turn repeated successful action sequences into skills instead of re-prompting
  them from scratch each time.

This is the skillification rule: when the master agent or a subagent repeats a
sequence of actions often enough that it becomes a reusable procedure, convert
that procedure into a `SKILL.md` and make future agents load it on demand.
Local lookup on 2026-06-03 did not find a skill named exactly `skillify`, but
OpenClaw has `skill-creator` and Hermes has skill-authoring guidance. Possible
OS should either reuse those or create a dedicated `skillify` skill once the
first repeated procedure is clear.

## Lessons From Current References

### OpenAI Self-Improving Agents

OpenAI's self-improving tax-agent pattern is:

production trace -> practitioner correction -> grouped finding -> eval target
-> bounded Codex task -> validated product change -> new production evidence.

Important lesson for Possible OS:

Do not turn every event into a code change. First capture evidence. Then group
repeated patterns. Then create evals. Then ask a coding agent to improve a
bounded surface with clear validation.

### OpenAI Codex Safety

OpenAI's Codex safety guidance emphasizes bounded execution, approval policies,
network controls, credential boundaries, and agent-native telemetry.

Important lesson for Possible OS:

The master agent can be powerful, but every tool and subagent must have explicit
permissions, forbidden actions, and audit trails.

### Anthropic Multi-Agent Research

Anthropic's research system uses an orchestrator-worker pattern:

- a lead agent plans;
- subagents explore separate branches in parallel;
- subagents return compressed findings;
- the lead agent synthesizes;
- more subagents are created only if needed.

Important lesson for Possible OS:

Subagents are most useful when work can be parallelized, when context exceeds
one model window, or when different tools/perspectives are needed. They are not
free. Multi-agent systems can burn many more tokens than single-agent workflows,
so the master agent should allocate subagents only when the expected value is
high enough.

Anthropic also notes that each subagent needs:

- a clear objective;
- an output format;
- tool/source guidance;
- boundaries;
- enough context to avoid duplicate or irrelevant work.

### Anthropic Evals

Anthropic's eval guidance distinguishes:

- transcript or trace: the full record of the agent's steps;
- outcome: the final state in the environment;
- eval harness: the infrastructure that runs and grades tasks.

Important lesson for Possible OS:

Self-improvement needs both traces and outcomes. A trace tells what happened.
An outcome tells whether it worked.

### Claude Code Best Practices

Claude Code guidance emphasizes giving agents verifiable checks, managing
context, using skills, using subagents for investigation, and running multiple
sessions/worktrees when parallelism is useful.

Important lesson for Possible OS:

Every delegated task should include verification criteria. The master agent
should inspect evidence, not just accept a worker's self-report.

### Local OpenClaw Patterns

OpenClaw Neo's local `AGENTS.md` uses:

- `SOUL.md` for identity;
- `USER.md` for user context;
- `memory/YYYY-MM-DD.md` for recent notes;
- `MEMORY.md` for curated long-term memory;
- `HEARTBEAT.md` as a small recurring checklist;
- `memory/heartbeat-state.json` to track periodic checks.

It distinguishes heartbeat from cron:

- heartbeat is good when timing can drift and checks can be batched;
- cron is better when exact timing matters or the job needs isolation.

Important lesson for Possible OS:

Use heartbeat for frequent situational awareness and opportunistic background
work. Use durable scheduled jobs for exact sends, exact audits, and long-running
isolated tasks.

## Current Heartbeat Context

As of 2026-06-04, the master heartbeat status call uses:

- `app/skills/master-agent-status/SKILL.md` as the stable system prompt;
- `soul.compact.md` in `stable_context.compact_soul` at the beginning of the
  JSON user payload;
- volatile task-board, report, event, config, and wake-time state after the
  stable context;
- full `soul.md` only as protected metadata: path, loaded flag, hash, character
  count, and non-edit rule.

This gives the status writer actual constitutional guidance while keeping the
full soul protected and avoiding repeated full-document prompt stuffing. It also
keeps the stable prefix more cache-friendly: skill instructions and compact soul
come before fast-changing heartbeat observations.

The heartbeat context now avoids feeding prior heartbeat prose directly back
into the LLM. Recent `master_heartbeat_completed` messages are compressed into
`recent_heartbeat_summary`, while `recent_events` is reserved for operational
events such as config changes, task creation, reports, and worker status
changes. This reduces status echo.

The context also includes `queue_analysis`, which marks queued work that has
exceeded a queue-age threshold and identifies tasks assigned to agents without a
registered runner. A queued task should not be described as simply "ready" after
it has aged past the threshold without being claimed.

The heartbeat now writes a durable `master_goals` row on each run. This first
goal synthesizer is deterministic: it prioritizes stale queued work, missing
runner capabilities, SystemsHealth observation, report-to-finding conversion,
and then general discovery. Later versions can replace this with an LLM-backed
goal synthesizer once evals and guardrails exist.

## Current SystemsHealthAgent Slice

As of 2026-06-04, SystemsHealthAgent has a first read-only worker:

- claims one queued SystemsHealthAgent task;
- checks backend/frontend service state;
- reads bounded recent backend/frontend journals;
- checks the backend `/health` endpoint;
- reads recent `agent_task_events`;
- reads recent `product_traces`;
- reads `git status --short`;
- redacts likely secrets from command samples;
- writes an `agent_reports` row;
- marks the task completed through the report path.

It must not:

- edit code;
- restart services;
- send emails;
- place calls;
- modify mailboxes;
- modify external systems;
- run destructive git commands.

This is intentionally an observe/report slice. Coding-task creation from health
findings remains a later reviewed slice.

## Current Capability Registry Slice

The master agent now has a first durable capability registry in
`agent_capabilities`.

Capabilities are currently declared from a conservative static list and can be
refreshed with safe probes. Actionful commands, such as running a heartbeat or
running a worker, are declared but not executed as probes. Each capability
records:

- name;
- type;
- source;
- purpose;
- risk level;
- whether approval is required;
- whether autonomous use is allowed;
- command metadata;
- last verification status and time.

This is the first step toward replacing hardcoded `capabilities_today` with a
live, discoverable tool inventory.

OpenClaw's memory-core plugin also has a pre-compaction memory flush pattern:
store durable notes in the current daily memory file, append-only, while keeping
bootstrap/source files read-only.

### Local Hermes Patterns

Hermes has:

- persistent config with gateway notify intervals, retries, context compression,
  checkpoint settings, and persistent shell settings;
- memory files under `/root/.hermes/memories`;
- cron tools for durable scheduled jobs;
- delegation for bounded subagent tasks;
- kanban for durable multi-agent task queues;
- worker heartbeat/comment tools;
- isolated worktree patterns for coding lanes.

Hermes' useful ownership rule:

The parent agent owns lifecycle, reconciliation, verification, and final handoff.
A worker or coding lane is an input, not a completion signal.

Important lesson for Possible OS:

The master agent must own final acceptance. Subagents can investigate, draft,
implement, and report, but the master checks the work, links outcomes, and
updates durable state.

## Core Components

The system needs these durable components:

1. `soul.md` constitution.
2. Tool registry.
3. Sensory system.
4. Trace ledger.
5. Memory system.
6. OODA runtime.
7. Subagent system.
8. Heartbeat system.
9. Action system.
10. Learning findings.
11. Eval system.
12. Experiment system.
13. Codex/task-packet system.
14. Web learning scout.
15. Dashboards and reports.
16. Master-agent chat and steering surface.
17. Approval and risk gates.

## 1. Constitution

File:

```text
soul.md
```

Rules:

- `soul.md` defines identity, values, taste, operating doctrine, and forbidden
  drift.
- The master agent may read it on each important run.
- The master agent may cite it.
- The master agent may propose diffs to it.
- The master agent may not edit it unless Pranav explicitly asks.

The constitution prevents self-improvement from becoming goal mutation.

## 2. Tool Registry

The master agent needs to know what apps on this machine can do.

Suggested table:

```text
agent_tools
- id
- name
- tool_type
- repo_path
- api_endpoint
- cli_command
- owner
- allowed_actions_json
- forbidden_actions_json
- risk_level
- health_status
- last_seen_at
- last_success_at
- notes_json
```

Examples:

- Possible OS backend: read/write product state, but production mutations may
  need approval depending on risk.
- Zoho Mail: read inbound/sent and send approved outreach.
- Front Precise inbox: read-only forever, never modify/delete/send.
- OpenClaw gateway: LLM/tool gateway and operational automation.
- Codex CLI: code improvement worker.
- SEO crawler: audit getpossibleminds.com and create action proposals.
- Git repos: inspect, patch, test, commit, push depending on explicit task and
  risk level.

## 3. Sensory System

The master agent should observe:

- product traces;
- user actions in Possible OS;
- pending operator actions;
- lead-gen daily plans;
- generated drafts;
- sent emails;
- Zoho inbound replies;
- Zoho sent history;
- Front read-only inbox context;
- opens, clicks, bounces, and delivery events;
- consult bookings;
- qualified conversation status;
- SEO/AEO audit output;
- code changes and git state;
- systemd service health;
- logs and errors;
- todos;
- web articles from OpenAI, Anthropic, and other relevant builders.

Signals should be separated into two major classes.

### User Judgment Signals

These show what Pranav values:

- approves an action;
- edits a draft;
- regenerates a draft;
- rejects a recommendation;
- changes a budget;
- selects a composer variant;
- marks an action done;
- leaves a note;
- asks a correction in chat.

### Market Outcome Signals

These show what reality rewards:

- email delivered;
- email bounced;
- opened;
- clicked;
- replied;
- booked consult;
- qualified conversation;
- unsubscribe;
- no response;
- revenue;
- customer result.

The distinction matters. If the system only learns from Pranav, it becomes a
preference mimic. If it only learns from market outcomes, it can become an
optimizer without taste or ethics. The cybernetic system should ask:

- What did the user correct?
- What did the market reward?
- Where do they agree?
- Where do they conflict?

## 4. Trace Ledger

Possible OS already has `product_traces`. This should become the universal
AI-legible event ledger.

Traces should capture:

- what was proposed;
- what context was used;
- what the agent saw;
- what the user saw;
- what changed;
- what was finally done;
- what happened later.

Example trace chain for one email:

```text
contact_selected
email_context_built
email_composed
operator_action_created
operator_action_opened
draft_edited
send_requested
email_sent
link_opened
reply_received
consult_booked
qualified_conversation_recorded
```

The master agent and subagents should emit traces too:

```text
master_heartbeat_started
master_observation_collected
master_decision_made
subagent_task_created
subagent_task_accepted
subagent_heartbeat_received
subagent_report_received
subagent_artifact_reviewed
finding_generated
eval_case_created
codex_task_packet_exported
code_change_applied
post_change_measurement_recorded
```

## 5. Memory System

Memory should have layers.

### Raw Event Memory

Database traces, logs, task events, email events, and app events.

This is high-volume and append-only.

### Daily Working Memory

File pattern:

```text
memory/YYYY-MM-DD.md
```

Purpose:

- record notable events from heartbeat runs;
- record decisions;
- record anomalies;
- record things to revisit;
- keep raw narrative continuity.

This mirrors the useful OpenClaw Neo pattern.

### Curated Long-Term Memory

File:

```text
MEMORY.md
```

Purpose:

- distilled lessons;
- stable preferences;
- known constraints;
- durable operating knowledge.

### Skills

Skills are procedural memory.

Examples:

- lead email composer skill;
- contact curation skill;
- inbox triage skill;
- SEO action generation skill;
- self-improvement task-packet skill;
- web learning scout skill.

### Concept Notes

Periodic web reading should produce concept notes:

```text
docs/learning-notes/YYYY-MM-DD-openai-self-improving-agents.md
docs/learning-notes/YYYY-MM-DD-anthropic-multi-agent-research.md
```

These notes should include:

- source URL;
- publication date;
- important idea;
- whether it applies to Possible OS;
- proposed product change;
- proposed eval;
- status: noted, proposed, accepted, rejected, implemented.

## 6. OODA Runtime

The master agent should run a recurring OODA loop.

### Observe

Collect:

- active alerts;
- pending actions;
- stale subagents;
- last heartbeat status;
- lead-gen metrics;
- inbox replies;
- bounces;
- consult bookings;
- trace findings;
- current todos;
- system health;
- recent web source updates.

### Orient

Use:

- `soul.md`;
- current company goals;
- memory;
- dashboards;
- recent user judgment;
- market outcomes;
- active risks;
- current constraints.

### Decide

Choose:

- what to do now;
- what to delegate;
- what to defer;
- what needs approval;
- what needs a finding/eval before action.

### Act

Actions include:

- create operator action;
- send approved email;
- generate today's lead list;
- draft reply;
- create SEO action;
- spawn subagent;
- run audit;
- export Codex task packet;
- update skill;
- create eval;
- restart service;
- write report.

### Learn

After action, link outcomes back to decisions:

- did user edit it?
- did user approve it?
- did market respond?
- did it break?
- did it save time?
- did it create revenue?
- should a skill/policy/code path change?

## 7. Subagent System

The master agent needs a subagent system because the company has more context
and work than one model window can hold.

The master should delegate when:

- the task can be parallelized;
- the task needs specialized context;
- the task needs a different toolset;
- the task can run independently;
- the expected value is high enough to justify token/tool cost.

The master should not delegate when:

- a direct edit is faster;
- the work requires founder judgment;
- the task is tightly coupled to another task;
- the subagent would need risky permissions;
- verification is unavailable.

### Suggested Subagents

```text
LeadGenAgent
InboxAgent
SEOAgent
ResearchScoutAgent
CodeImprovementAgent
SystemsHealthAgent
DocumentationMemoryAgent
ExperimentAgent
FinanceOpsAgent
CustomerSuccessAgent
```

### Subagent Registry

Suggested table:

```text
agent_registry
- id
- name
- role
- description
- allowed_tools_json
- forbidden_tools_json
- allowed_repos_json
- risk_level
- max_parallel_tasks
- default_timeout_seconds
- heartbeat_interval_seconds
- status
- created_at
- updated_at
```

### Delegation Packet

Every delegated task should be explicit.

Suggested table:

```text
agent_tasks
- id
- parent_task_id
- assigned_agent_id
- title
- objective
- context_json
- allowed_tools_json
- forbidden_actions_json
- input_artifacts_json
- expected_output_schema_json
- acceptance_criteria_json
- verification_commands_json
- risk_level
- requires_human_approval
- status
- priority
- deadline_at
- heartbeat_interval_seconds
- claimed_at
- completed_at
- created_at
- updated_at
```

The packet should include:

- objective;
- why this task matters;
- relevant context;
- what not to do;
- exact tool permissions;
- expected report format;
- artifacts to create;
- how often to report status;
- timeout/deadline;
- acceptance criteria;
- verification commands.

Example:

```text
Task: Research OpenAI/Anthropic posts on self-improving agents this week.
Agent: ResearchScoutAgent
Allowed: web search, read docs, write concept note.
Forbidden: edit code, send email, modify app state.
Output: 5 source summaries, 3 possible product ideas, 1 recommended next eval.
Deadline: 15 minutes.
Report every: 5 minutes.
Acceptance: every claim has source URL; no product change is applied directly.
```

### Subagent Statuses

```text
queued
accepted
running
waiting_on_tool
waiting_on_user
blocked
completed
failed
cancelled
stale
```

### Subagent Events

Suggested table:

```text
agent_task_events
- id
- task_id
- agent_id
- event_type
- message
- input_json
- output_json
- metadata_json
- created_at
```

Events:

```text
task_created
task_claimed
heartbeat
progress_report
artifact_created
needs_clarification
blocked
completed
failed
cancelled
reviewed_by_master
accepted_by_master
rejected_by_master
```

### Report Back Format

Every subagent report should be structured:

```json
{
  "task_id": "...",
  "status": "completed",
  "summary": "...",
  "key_findings": [],
  "actions_taken": [],
  "artifacts": [],
  "evidence": [],
  "verification": [],
  "risks": [],
  "open_questions": [],
  "recommended_next_actions": []
}
```

The master must treat this as evidence, not truth. It should inspect artifacts,
rerun checks when possible, and only then mark the task accepted.

### Delegation Rules

1. The master owns lifecycle.
2. The master owns final acceptance.
3. Subagents cannot edit `soul.md`.
4. Subagents cannot perform external actions unless explicitly allowed.
5. Subagents cannot mark their own work as finally accepted.
6. Code-writing subagents must use isolated worktrees/branches when practical.
7. Risky actions require user approval.
8. Every delegated task must be traceable.
9. Every worker should report heartbeat/progress on schedule.
10. Stale workers are reclaimed, cancelled, or escalated.

## 8. Heartbeat System

The master agent should wake every few minutes.

The heartbeat is the lightweight pulse of the system. It should not do heavy
analysis every time. It should check status, notice drift, and trigger bounded
work.

Recommended default:

```text
Every 5 minutes:
- check subagent status;
- check stale tasks;
- check pending approvals;
- check urgent inbound replies;
- check failed sends/system errors;
- update heartbeat state;
- stay quiet if nothing matters.
```

Heavier loops:

```text
Every hour:
- summarize active loops;
- sync outcomes;
- update dashboards;
- check lead-gen progress;
- check SEO/actions progress.

Daily:
- generate daily OODA report;
- run learning finding analysis;
- review todos;
- consider self-improvements;
- check official OpenAI/Anthropic sources for useful articles;
- propose one or more improvements if evidence supports them.

Weekly:
- curate memory;
- review skill performance;
- prune/merge stale docs;
- compare before/after metrics for shipped improvements.
```

Current heartbeat status implementation:

- builds a bounded wake context packet on every heartbeat;
- calls the OpenClaw gateway with
  `app/skills/master-agent-status/SKILL.md`;
- asks the model for JSON containing state, goal, current focus, intended next
  steps, what Pranav needs to do, confidence, and reasoning;
- records whether the status was written by the LLM or by fallback logic;
- if the gateway fails, records the error and keeps the heartbeat alive with a
  deterministic fallback status;
- may auto-delegate one safe internal next-slice task when the task board is
  idle. Current V1 delegates a queued SystemsHealthAgent observation/delegation
  task but does not run that worker or edit code;
- shows the human status and full wake context in `/agents`.

The current goal in the wake context comes from a bootstrap mission inside
`app/services/master_agent.py::_build_wake_context`. The durable version should
load the goal from `master_plans` and `master_plan_items` once those exist.

### Heartbeat State

Suggested file:

```text
memory/heartbeat-state.json
```

Suggested shape:

```json
{
  "lastChecks": {
    "subagents": "2026-06-03T14:00:00Z",
    "inbox": "2026-06-03T14:00:00Z",
    "lead_gen": "2026-06-03T13:55:00Z",
    "seo": "2026-06-03T12:00:00Z",
    "web_learning": "2026-06-03T09:00:00Z",
    "memory_curation": "2026-06-01T09:00:00Z"
  },
  "quietUntil": null,
  "lastUserVisibleReportAt": "2026-06-03T10:00:00Z"
}
```

### Heartbeat Checklist

Suggested file:

```text
HEARTBEAT.md
```

Keep it small. It should contain only active recurring checks and reminders.

Example:

```text
# HEARTBEAT.md

- Check stale subagent tasks every 5 minutes.
- Check urgent inbound lead-gen replies every 5 minutes.
- Sync outcomes hourly.
- Run web learning scout daily.
- If no meaningful update exists, stay quiet.
```

### Heartbeat vs Cron

Use heartbeat when:

- timing can drift;
- tasks can be batched;
- context from recent runs matters;
- the goal is awareness, not exact execution.

Use cron/scheduled jobs when:

- exact timing matters;
- a task needs isolation;
- an external action must occur at a precise time;
- a long-running process should not depend on an interactive session.

Email sending should use scheduler semantics. Awareness and learning can use
heartbeat semantics.

## 9. Web Learning Scout

The master agent should periodically read the web for new ideas on
self-improving systems.

Initial source scope:

- OpenAI engineering/research posts;
- Anthropic engineering/research posts;
- official docs on agents, evals, traces, memory, subagents, and safety;
- selected open-source agent repos when relevant.

Suggested table:

```text
agent_web_sources
- id
- source_name
- url
- domain
- source_type
- title
- published_at
- discovered_at
- last_checked_at
- summary
- key_ideas_json
- possible_os_implications_json
- proposed_actions_json
- status
```

Daily scout output:

```text
docs/learning-notes/YYYY-MM-DD-web-learning.md
```

The scout should answer:

- What is new?
- Is it credible?
- What is the important idea?
- Does it apply to Possible OS?
- What feature, eval, skill, or policy should be considered?
- What should not be copied?

The scout should create proposals, not silently mutate the system.

## 10. Action System

Actions should remain operator-facing pointers and approval surfaces.

The master agent can create actions such as:

- approve this email draft;
- review this reply;
- approve this SEO change;
- review this learning finding;
- approve this Codex task packet;
- inspect this subagent report;
- approve this code change.

Execution should happen in the owning workflow, not in a generic action list,
unless the action itself is generic.

## 11. Learning Findings

The system should periodically group repeated signals into findings.

Examples:

- Pranav repeatedly edits first-touch emails to mention Precise Imaging earlier.
- A composer variant gets more approvals and fewer manual edits.
- Generic clinic inboxes bounce often.
- A subagent repeatedly stalls because its task packet lacks output schema.
- SEO actions about schema markup are often accepted, but thin title rewrites
  are often ignored.

Suggested table:

```text
improvement_findings
- id
- workflow
- finding_type
- summary
- evidence_trace_ids
- evidence_task_ids
- source_signal_type
- severity
- confidence
- suggested_change
- status
- created_at
- reviewed_at
```

Findings should separate:

- user judgment evidence;
- market outcome evidence;
- technical reliability evidence;
- cost/latency evidence.

## 12. Eval System

Every accepted finding should become an eval before becoming a system change
when practical.

Examples:

Email composer eval:

```text
Input:
First-touch PI firm lead sourced from Precise-related inboxes.

Expected:
Email uses a clear Precise Imaging proof point early, without overclaiming,
without em dashes, and with the consult link in the signature.
```

Subagent delegation eval:

```text
Input:
Research task with three separate branches.

Expected:
Master creates distinct task packets with non-overlapping objectives, output
schemas, and deadlines.
```

Heartbeat eval:

```text
Input:
One stale worker, one normal worker, one urgent inbound reply.

Expected:
Master escalates stale worker, leaves normal worker alone, and creates an
operator action for the urgent reply.
```

## 13. Codex Task Packets

When a finding is accepted, the system should create a bounded task packet.

Suggested path:

```text
data/codex_tasks/YYYY-MM-DD-short-title/
  TASK.md
  traces.json
  eval_cases.json
  relevant_files.md
  validation_commands.md
  expected_behavior.md
```

Rules:

- production evidence is read-only;
- writable work happens in a repo/worktree;
- validation commands are explicit;
- risk boundaries are explicit;
- Codex output is not accepted until reviewed and verified.

This follows the OpenAI pattern: traces and practitioner/user corrections become
scoped, eval-backed engineering work.

## 14. Dashboards

Dashboards should make learning legible.

### Master Agent Dashboard

Show:

- current OODA state;
- active priorities;
- pending decisions;
- active subagents;
- stale subagents;
- last heartbeat;
- next scheduled heartbeat;
- recent reports;
- risky pending actions.

### Subagent Dashboard

Show:

- task queue;
- agent status;
- last heartbeat;
- reports;
- artifacts;
- blocked tasks;
- completed tasks awaiting review.

### Log Observation And Bug Correction

The master agent should eventually see the whole app's operational health, but
through a bounded read-only log observation layer rather than unbounded raw log
dumps.

Sources should include:

- backend systemd journal for `autocaller-backend.service`;
- frontend systemd journal and `/var/log/autocaller-frontend.log`;
- product traces;
- agent task events and reports;
- API errors;
- build, type-check, and test outputs;
- browser/render checks when available;
- deployment/restart history.

The master agent should use these logs to:

- detect recurring errors;
- summarize anomalies;
- redact or avoid secrets;
- create improvement findings or bug todos;
- delegate code fixes to a coding subagent with exact evidence;
- verify fixes with explicit commands before reporting completion.

The future `SystemsHealthAgent` should own this slice. It should be read-only
until it creates a bounded coding-subagent task. The coding subagent may propose
or implement a fix, but the master agent must verify the diff and tests before
accepting it.

### Learning Dashboard

Show:

- findings by status;
- evals by workflow;
- Codex task packets;
- shipped improvements;
- post-change measurements.

### Lead-Gen Learning Dashboard

Show by 1 day, 7 days, 30 days, and 90 days:

- manual edit rate;
- approval rate;
- rejection rate;
- regeneration rate;
- bounce rate;
- reply rate;
- click rate;
- booked qualified conversations;
- variant performance;
- contact-selection performance.

## 15. Master-Agent Chat

Possible OS needs a first-class chat surface for the master agent.

This is not ordinary support chat. It is the strategic and operational control
plane for the company. The master agent should have enough progressively loaded
context to answer questions about:

- self-improvement and system development;
- strategy;
- current operations;
- procedures;
- status;
- subagent activity;
- blockers;
- what was accomplished today;
- how Pranav can help.

The chat should be able to steer short-term and long-term plans. A conversation
with Pranav should create durable effects when appropriate:

- update a short-term plan;
- update a long-term plan;
- create or reprioritize todos;
- create or change an agent task;
- create operator actions;
- create learning findings;
- create Codex task packets;
- add procedural memory to a skill;
- write a daily report.

The chat should use progressive disclosure:

- start with `soul.md` hash/rule and current operational summary;
- load relevant plans, tasks, traces, docs, and skills only when needed;
- cite or link the durable source of truth when answering;
- write important decisions back into durable memory.

### Daily Master-Agent Report

Once per day, the master agent should produce a concise report answering:

- What did I get done today?
- What are the blockers?
- How can you as a user/human help me?

The daily report should use:

- `product_traces`;
- `agent_tasks`;
- `agent_task_events`;
- `agent_reports`;
- `operator_notifications`;
- lead-gen activity;
- todos;
- commits/code changes when relevant;
- market feedback such as replies, bounces, clicks, and bookings.

The report should be persisted, not only shown transiently. Recommended future
storage:

```text
daily_master_reports
- id
- report_date
- summary
- accomplishments_json
- blockers_json
- human_help_requests_json
- evidence_json
- created_at
```

It can also write a readable markdown artifact under:

```text
docs/daily-reports/YYYY-MM-DD-master-agent.md
```

### Long-Term And Short-Term Plans

The master agent needs to hold long-term plans in parallel with short-term
activities.

Short-term activity examples:

- send approved emails;
- generate today's lead-gen actions;
- write a blog post;
- triage inbound replies;
- create SEO actions;
- run a heartbeat check.

Long-term plan examples:

- build the master-agent chat system;
- improve contact selection;
- learn the personal injury domain;
- build the ResearchScout loop;
- improve email composer variants;
- create durable evaluation suites;
- skillify repeated workflows.

These should not compete inside one flat todo list. Future implementation should
add plan objects:

```text
master_plans
- id
- horizon              short_term | long_term
- title
- objective
- strategy
- status
- priority
- owner_agent
- success_metrics_json
- constraints_json
- created_at
- updated_at

master_plan_items
- id
- plan_id
- title
- status
- sequence_index
- linked_task_id
- linked_todo_id
- linked_finding_id
- linked_trace_ids
- created_at
- updated_at
```

The heartbeat should check both:

- short-term execution state;
- long-term plan progress.

The chat should let Pranav steer both:

- "Today, prioritize lead-gen emails over SEO."
- "This week, focus the master agent on learning the PI domain."
- "Pause blog posts until the email loop is stable."
- "Create a plan to make contact selection self-improving."

This lets Possible OS run parallel loops without losing strategic continuity.

## 16. Build Sequence

### Phase 1: Persistent Design And Runtime Skeleton

- Create this design doc.
- Create/confirm `soul.md`.
- Create `HEARTBEAT.md`.
- Create `memory/heartbeat-state.json`.
- Add DB schema for `agent_registry`, `agent_tasks`,
  `agent_task_events`, `agent_reports`, and `agent_artifacts`.

### Phase 2: Subagent Task Board

- Add backend APIs to create/list/update subagent tasks.
- Add status/heartbeat/report endpoints.
- Add `/agents` UI page.
- Add action notifications for blocked or review-needed subagent work.

### Phase 3: Master Heartbeat

- Add a scheduler job that wakes every 5 minutes.
- On each wake, run lightweight checks.
- Record `master_heartbeat_started` and `master_heartbeat_completed` traces.
- Check stale subagents.
- Create operator actions for urgent decisions.
- Stay quiet when no action matters.

### Phase 4: First Worker Agents

Start with safe subagents:

- ResearchScoutAgent: web/source reading, writes notes, no product mutation.
- SystemsHealthAgent: checks service health and logs, creates reports and bug-fix
  delegation packets.
- DocumentationMemoryAgent: curates docs/memory proposals, no direct changes to
  `soul.md`.

Then add higher-impact agents:

- LeadGenAgent.
- InboxAgent.
- SEOAgent.
- CodeImprovementAgent.

### Phase 5: Web Learning Scout

- Daily official-source scan.
- Store sources and summaries.
- Create concept notes.
- Generate improvement proposals, not automatic changes.

### Phase 6: Learning Findings And Evals

- Extend existing learning endpoints to include subagent and heartbeat traces.
- Detect repeated delegation failures.
- Detect repeated user corrections.
- Detect repeated market outcome patterns.
- Create eval cases.

### Phase 7: Self-Improvement Loop

- Export Codex task packets from accepted findings.
- Run bounded coding tasks in isolated worktrees when appropriate.
- Run evals and regression tests.
- Require human approval for risky changes.
- Measure post-change outcomes.

## 17. Minimal V1

The smallest useful V1:

1. Add `agent_tasks` and `agent_task_events`.
2. Add `/agents` page.
3. Add a 5-minute heartbeat job.
4. Let the master create and monitor ResearchScoutAgent tasks.
5. Let ResearchScoutAgent write web-learning notes.
6. Let the master create findings from those notes.
7. Let Pranav approve or reject proposed improvements.

That gives the system a real pulse without giving it uncontrolled power.

## 18. Non-Negotiable Constraints

- Never edit `soul.md` without explicit founder instruction.
- Never use Front credentials to modify, delete, archive, or send.
- Never send outreach without the current approval policy allowing it.
- Never treat subagent self-report as verification.
- Never let workers mutate durable learning state without traceable events.
- Never hide risky actions inside "automation."
- Never optimize only for email metrics while ignoring user judgment and brand
  quality.

## Source Notes

Current web sources checked on 2026-06-03:

- OpenAI, "Building self-improving tax agents with Codex", 2026-05-27.
- OpenAI, "Running Codex safely at OpenAI", 2026-05-08.
- Anthropic, "How we built our multi-agent research system".
- Anthropic, "Demystifying evals for AI agents".
- Anthropic/Claude Code docs, "Best practices for Claude Code".

Local systems inspected on this machine:

- `/root/openclaw-neo/AGENTS.md`
- `/root/openclaw-neo/HEARTBEAT.md`
- `/root/openclaw-neo/MEMORY.md`
- `/root/openclaw-hunter/AGENTS.md`
- `/root/.hermes/config.yaml`
- `/root/.hermes/memories/MEMORY.md`
- `/root/.hermes/skills/autonomous-ai-agents/hermes-agent/SKILL.md`
- `/root/.hermes/skills/autonomous-ai-agents/kanban-codex-lane/SKILL.md`
- `/usr/lib/node_modules/openclaw/dist/extensions/memory-core/index.js`
- `/usr/lib/node_modules/openclaw/dist/extensions/active-memory/index.js`
- `/usr/lib/node_modules/openclaw/dist/extensions/memory-wiki/index.js`
