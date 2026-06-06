# Master Agent Context Design For The Two Prime Directives

Design the master-agent wake context as a control cockpit, not a memory dump.

The two prime directives should be the first stable thing the agent sees every
time it wakes up.

## Prime Directives

Always first:

```md
Prime directives:
1. Move fast toward the user's stated short-term and long-term goals,
   effectively and efficiently.
2. Maintain and improve a good mental model of how the system works and how it
   can improve over short and long horizons.
```

Everything else is subordinate to these objectives.

The Elon Musk algorithm, systems thinking, complexity thinking, OODA loop,
subagents, traces, skills, dashboards, and self-improvement machinery are all
tools in service of these two directives. They are not independent goals.

## Recommended Context Order

### 1. Prime Directives

Put the prime directives before `soul.compact.md`, mission text, recent events,
tasks, or capabilities.

Reason:

The model should orient around the highest-level objective before it sees any
operational detail. If it sees implementation details first, it may optimize for
local maintenance work instead of the user's real goal.

### 2. Current User-Stated Goals

Separate goals by horizon:

```json
{
  "short_term_goal": "Send approved lead-gen emails through the master-agent heartbeat.",
  "medium_term_goal": "Build a cybernetic lead-gen loop.",
  "long_term_goal": "Build Possible OS as a self-improving operating system for Possible Minds."
}
```

This prevents the agent from drifting into generic system-health work when
there is an active user goal.

The goal stack should include:

- short-term goal;
- medium-term goal;
- long-term goal;
- source of the goal;
- when it was set;
- success metric;
- expiry or review time;
- whether it was set by the user, synthesized by the system, or inferred from
  recent activity.

### 3. Current Operating State

The agent needs a compact state snapshot:

```json
{
  "heartbeat_enabled": false,
  "auto_send_enabled": true,
  "approved_email_actions": 3,
  "last_email_sent": "2026-06-04T17:45:30Z",
  "blocked_tasks": [],
  "recent_failures": [],
  "current_risk": "Approved sends can happen on manual heartbeat."
}
```

This helps the agent answer:

- what is happening now?
- what can move now?
- what is blocked?
- what changed since the last wake?
- what risk needs attention?

### 4. Mental Model

Add a durable section that explains how the system currently works:

```json
{
  "system_model": {
    "lead_gen_loop": "select contacts -> compose drafts -> user approves -> heartbeat sends -> observe outcomes -> learn",
    "email_send_path": "agent_action -> policy check -> Zoho send -> email_logs -> action execution_result",
    "learning_loop": "traces + user edits + market outcomes -> findings -> evals -> code/skill changes",
    "known_gaps": [
      "outcomes are not fully linked back to sends",
      "subagent execution is still shallow",
      "goal planner is partly deterministic"
    ]
  }
}
```

This directly serves the second prime directive.

The system model should not be prose fluff. It should be a compact map of:

- major loops;
- source-of-truth tables;
- important services;
- current capabilities;
- known gaps;
- recent architecture changes;
- current assumptions;
- things the agent should verify before acting.

### 5. Recent Evidence

Do not give only prose summaries. Give facts:

```json
{
  "recent_evidence": [
    {
      "type": "email_sent",
      "recipient": "matt@bikelegalfirm.com",
      "status": "sent",
      "email_log_id": "1f11d8fc0b074a3e8165a2096e3b18ae",
      "lesson": "approved-send path works"
    }
  ]
}
```

Recent evidence should include:

- actions executed;
- sends attempted;
- sends succeeded;
- sends failed;
- replies observed;
- user approvals;
- user edits;
- user rejections;
- subagent reports;
- system errors;
- changed code or skill files;
- newly discovered constraints.

This is the bridge between "what the agent believes" and "what actually
happened."

### 6. Capabilities And Constraints

The agent should know what it can do:

```json
{
  "can_do": [
    "run heartbeat",
    "execute approved lead-gen sends",
    "inspect actions",
    "create subagent tasks",
    "read traces"
  ],
  "cannot_do_without_approval": [
    "edit soul.md",
    "send unapproved emails",
    "delete data",
    "modify read-only inboxes"
  ]
}
```

Capabilities should be specific, not abstract.

Bad:

```json
{
  "can_do": ["use CLI"]
}
```

Better:

```json
{
  "can_do": [
    {
      "name": "execute approved lead-gen email actions",
      "command": "bin/autocaller actions execute-approved-lead-gen --limit=1 --actor=master-agent --json",
      "risk": "high",
      "approval_required": true,
      "autonomous_allowed_when": "auto_execute_approved_lead_gen_email_enabled is true"
    }
  ]
}
```

### 7. Decision Frame

End the context with the questions it must answer every wake:

```md
On every wake:
1. What is the user's most important stated goal right now?
2. What is the fastest safe next move toward it?
3. What does the current system state say is blocking progress?
4. What did we learn since the last wake?
5. Should the system model, skill, code, eval, or plan be updated?
6. What should be done now, delegated, postponed, or escalated to the user?
```

This gives the model a repeatable operating discipline.

## Three Context Layers

Use three layers.

### Stable Prefix

Stable prefix should include:

- prime directives;
- compact soul;
- operating doctrine;
- safety boundaries;
- decision questions;
- stable output schema;
- stable capability definitions;
- stable knowledge summaries.

This should change rarely.

Reason:

Stable prefix supports OpenAI prompt caching and keeps the agent's identity and
objective consistent. OpenAI prompt caching depends on exact prefix matches, so
the first large block sent to the model should be byte-stable across heartbeats
whenever possible.

Do not put these fields in the stable prefix:

- timestamps;
- `woke_at`;
- current action counts;
- last heartbeat status;
- `last_verified_at`;
- latest reports;
- recent traces;
- recent events;
- changing capability state;
- dynamic user answers;
- active goal status.

Those belong in volatile state.

For cache friendliness, stable prefix assembly should be deterministic:

- sort JSON keys;
- sort capability definitions by stable name;
- sort knowledge summaries by slug;
- include versions or hashes instead of dynamic `updated_at` timestamps;
- avoid rendering random UUIDs, current dates, or request IDs in the cached
  prefix.

### Durable Memory

Durable memory should include:

- active goal stack;
- long-term plans;
- system model;
- known gaps;
- current architecture map;
- capability registry;
- recurring lessons;
- current policies;
- accepted constraints.

This changes when the system learns something meaningful.

Reason:

Durable memory helps the agent preserve continuity across wakes without stuffing
every trace or old event into the prompt.

### Volatile State

Volatile state should include:

- latest heartbeat;
- recent actions;
- pending approved sends;
- recent replies;
- recent failures;
- queued tasks;
- blocked tasks;
- fresh traces;
- recent system health observations.

This changes every wake.

Reason:

Volatile state helps the agent act on the current situation.

## Practical Wake Context Shape

For OpenAI/Codex, the wake prompt should be assembled as two conceptual blocks:

1. `cached_static_context`
2. `volatile_wake_state`

The cached static context should appear first in the prompt. The volatile wake
state should come after it.

The wake context should roughly look like this:

```json
{
  "kind": "master_agent_wake_context_v2",
  "cached_static_context": {
    "prime_directives": [
      "Move fast toward the user's stated short-term and long-term goals, effectively and efficiently.",
      "Maintain and improve a good mental model of how the system works and how it can improve over short and long horizons."
    ],
    "soul_compact": {},
    "stable_operating_doctrine": {},
    "stable_output_schema": {},
    "stable_capability_definitions": [],
    "stable_knowledge_summaries": [],
    "wake_decision_questions": []
  },
  "volatile_wake_state": {
    "woke_at": "...",
    "actor": "master-agent",
    "goal_stack": {
      "short_term": {},
      "medium_term": {},
      "long_term": {}
    },
    "active_goal": {},
    "objective_status": {},
    "current_state": {},
    "recent_evidence": [],
    "capabilities_state": [],
    "open_questions": [],
    "current_tasks": [],
    "recent_actions": [],
    "recent_reports": [],
    "recent_events": []
  },
  "compatibility": {
    "active_goal": {},
    "recent_actions": [],
    "recent_reports": []
  }
}
```

The important change is not just adding fields. The important change is the
priority order:

1. cached static context;
2. volatile wake state;
3. compatibility fields for older UI/code paths.

Within cached static context:

1. prime directives;
2. compact soul;
3. stable doctrine;
4. stable output schema;
5. stable capability definitions;
6. stable knowledge summaries;
7. decision questions.

Within volatile wake state:

1. goal stack;
2. objective status;
3. current operating state;
4. recent evidence;
5. changing capability state;
6. open questions;
7. detailed traces and events.

## OpenAI Prompt Caching Design

OpenAI prompt caching is automatic, but it only helps when the beginning of the
prompt is an exact repeated prefix. The architecture should therefore optimize
for prefix stability.

Use this rule:

```text
Stable first, volatile last.
```

For the master agent, the reusable prefix should include:

- prime directives;
- compact soul;
- stable operating doctrine;
- stable output contract for the status writer;
- stable descriptions of available capabilities;
- stable summaries of knowledge-base pages.

The volatile suffix should include:

- current time;
- current goal status;
- recent actions;
- open questions;
- recent reports;
- fresh traces;
- latest capability verification state.

If the OpenAI/Codex call path supports passthrough request parameters, use a
stable cache key:

```json
{
  "prompt_cache_key": "possible-os-master-agent-v1",
  "prompt_cache_retention": "24h"
}
```

If the gateway does not support those parameters yet, the prompt should still
be assembled with an exact stable prefix so automatic prompt caching can work as
well as the gateway permits.

The heartbeat should log cache telemetry when the API returns it:

```json
{
  "prompt_tokens_details": {
    "cached_tokens": 1234
  }
}
```

Store this in heartbeat status metadata so cache effectiveness can be measured
over time.

## Why This Works

The first directive keeps the agent commercially and operationally useful. It
asks:

- What did the user want?
- What is the fastest safe path?
- What result matters?
- What is blocking motion?
- What can be executed now?

The second directive prevents blind speed. It asks:

- Do I understand how this system works?
- Is my model stale?
- What did reality just teach us?
- What part of the system should be improved?
- What should become a skill, eval, doc, trace, policy, or code change?

Together, they create the right tension:

- move fast;
- understand deeply;
- improve the system while pursuing the goal.

## Best Next Implementation

Add a new structured context builder section with:

1. `prime_directives`;
2. `goal_stack`;
3. `system_model`;
4. `current_state`;
5. `recent_evidence`;
6. `capabilities`;
7. `constraints`;
8. `wake_decision_questions`.

Then update `run_master_heartbeat()` so the wake context always places
`prime_directives` before `soul_compact`, mission, tasks, and recent events.

The first horizontal slice should not attempt a perfect memory system. It should
do this:

1. Add the two prime directives to the wake context.
2. Add a compact `goal_stack`.
3. Add a first `system_model` object with the current lead-gen loop, action
   execution loop, and learning loop.
4. Add `wake_decision_questions`.
5. Update the master-agent status skill so it explicitly answers:
   - how the next action serves the user goal;
   - what the current system model says;
   - what, if anything, should be improved.

That gives the master agent a stronger orientation without building a huge
planning system all at once.

## How The Master Agent Knows What The Previous Heartbeat Accomplished

Today it knows through five inputs in the next wake context.

### 1. Previous Heartbeat Event

Every completed heartbeat writes an `AgentTaskEventRow`:

```text
event_type = master_heartbeat_completed
input_json = wake context it received
output_json = what it decided, reported, or did
message = human-readable state summary
```

So the next heartbeat can inspect recent heartbeat events and see prior output.

### 2. Recent Durable Actions

On wake, it loads the latest durable actions through
`_recent_action_snapshots(...)`.

That includes:

```json
{
  "action_type": "send_email",
  "status": "succeeded",
  "input_summary": {
    "to": "...",
    "subject": "...",
    "test_email": true
  },
  "result_summary": {
    "sent_to": "...",
    "sent_message_id": "...",
    "sent_at": "...",
    "transport": "zoho_api",
    "email_log_id": "...",
    "email_log_status": "sent"
  }
}
```

This is the main way it knows what actually got done.

### 3. Goal Evidence

The wake context runs:

```python
_goal_evidence(active_goal, recent_actions)
```

Right now this is narrow. It specifically checks whether the active "test
email" goal was satisfied by a recent succeeded email action to
`pranav.modi@gmail.com`.

So for that goal, it can say:

```json
{
  "status": "satisfied",
  "matched_action_id": "...",
  "sent_to": "pranav.modi@gmail.com",
  "sent_message_id": "...",
  "sent_at": "..."
}
```

or:

```json
{
  "status": "not_yet_satisfied",
  "reason": "No recent succeeded send_test_email action matched..."
}
```

### 4. Task Board State

It loads current subagent tasks:

- queued;
- running;
- blocked;
- stale;
- completed reports.

So it can tell whether a delegated task finished, got stuck, or needs
escalation.

### 5. Recent Reports

It loads the latest `AgentReportRow` records.

This lets it see what subagents reported back, for example a SystemsHealthAgent
report.

## Current Gap

This is still partly shallow.

The system has evidence, but it does not yet have a clean interpreted objective
status layer for every goal.

The better design is to add an explicit `objective_status` section to every wake
context:

```json
{
  "objective_status": {
    "active_goal_id": "...",
    "goal": "...",
    "status": "satisfied | in_progress | blocked | stale | failed",
    "evidence": [
      {
        "type": "action_succeeded",
        "action_id": "...",
        "email_log_id": "...",
        "sent_at": "..."
      }
    ],
    "remaining_work": ["..."],
    "next_best_action": "..."
  }
}
```

That would make the agent's memory cleaner:

- previous heartbeat output is context;
- durable actions are proof;
- reports are evidence;
- objective status is the interpreted state.

The agent should not only know that something happened. It should know:

- what objective the action belonged to;
- whether the action advanced the objective;
- what evidence proves it;
- what remains;
- what the next best move is.

## Read-Only Filesystem Capability And Runner Loop

The master agent should have a generic sensory capability for inspecting its own
environment.

Do not create overly specific agents first, such as a one-off
`CodebaseInspectorAgent`. The better abstraction is:

```text
read-only filesystem inspection
```

This gives the master agent safe eyes that can be reused for codebase
understanding, debugging, documentation, planning, system-model updates, and
self-improvement.

### Read-Only Filesystem Inspection

The capability should expose structured operations, not arbitrary shell:

```text
list_files
read_file
search_text
git_status
git_diff
git_log
git_show
```

Inputs should be JSON-shaped operation requests:

```json
{
  "operation": "read_file",
  "path": "app/services/master_agent.py",
  "start_line": 1200,
  "end_line": 1400,
  "reason": "Understand heartbeat context construction."
}
```

The backend should reject raw command strings:

```json
{
  "command": "cat app/services/master_agent.py && rm -rf /"
}
```

Policy rules:

- root reads under `/home/pranav/autocaller`;
- use repo-relative paths at API and CLI boundaries;
- reject path traversal;
- reject binary files;
- reject writes, deletes, moves, redirects, package installs, service restarts,
  network calls, and arbitrary shell;
- cap output size;
- return `truncated=true` with a narrowing hint when output is too large;
- trace every operation, including actor, reason, paths, output size, and
  truncation.

This capability should appear in the capability registry as a medium-risk,
autonomous, read-only capability.

### Bounded Heartbeat Tool Runner Loop

Some heartbeat goals require multiple LLM/tool iterations in one wake cycle.

The architecture should support:

```text
wake up
-> build context
-> ask LLM what to do next
-> LLM requests structured read-only tool call
-> backend validates and executes tool call
-> tool result is appended to working context
-> LLM decides next step
-> repeat within budget
-> write report and continuation note
-> sleep
```

The heartbeat remains the scheduler. The runner loop is the bounded work engine.

V1 limits:

- only `filesystem_read` tool calls;
- no file modifications;
- max 5 tool calls per heartbeat;
- max 90 seconds runtime;
- max 50 KB output per tool call;
- bounded accumulated context;
- every tool call is traced;
- if the loop cannot finish, write continuation state and stop.

Continuation state should record:

```json
{
  "goal_id": "...",
  "status": "in_progress",
  "files_read": [],
  "facts_learned": [],
  "remaining_questions": [],
  "next_suggested_tool_call": {},
  "document_target": "docs/agent-kb/system-model/master-agent.md"
}
```

This is how the next heartbeat knows what happened without relying on hidden LLM
memory.

For the current codebase-understanding goal, the runner should be able to:

1. search for heartbeat and context functions;
2. read bounded snippets;
3. summarize what it learned;
4. propose first Markdown document sections;
5. write durable continuation state.

Writing or modifying Markdown should be a separate, explicitly approved write
capability unless the user authorizes a narrow document-write path.

## Human Question Capability And Knowledge Base Design

Yes, this makes sense.

The master agent needs four missing capabilities:

1. A generic read-only filesystem inspection capability.
2. A bounded multi-iteration LLM/tool runner loop inside heartbeat.
3. A way to ask the user for clarification, information, approval, or a real
   world action the agent cannot perform.
4. A knowledge base that stores and updates the agent's mental model of how
   Possible OS works.

These should be first-class system components, not just chat messages.

## Research Findings

The useful pattern across agent systems is layered memory, not one giant memory
blob.

OpenClaw's documented memory model uses plain Markdown files for durable
memory, daily notes for recent context, and an optional dreaming/consolidation
process to promote only high-signal items into long-term memory. Its docs also
describe memory plugins that add SQLite, hybrid search, vector search, and a
provenance-rich wiki layer.

Local OpenClaw on this machine follows that pattern:

- `SOUL.md` stores identity and constitution.
- `USER.md` stores who the agent is helping.
- `MEMORY.md` stores curated long-term facts and preferences.
- `memory/YYYY-MM-DD.md` stores daily notes.
- `HEARTBEAT.md` stores small recurring heartbeat instructions.
- `AGENTS.md` explicitly says "Text > Brain": if something should survive, it
  must be written to a file.

LangGraph's memory docs separate:

- short-term memory: thread/session state;
- long-term memory: cross-session facts and application-level knowledge;
- semantic memory: facts;
- episodic memory: experiences and past actions;
- procedural memory: instructions, prompts, skills, and repeatable behavior.

OpenAI's Agents SDK human-in-the-loop docs use an interruption pattern:

- a tool call can require approval;
- execution pauses;
- the pending interruption is returned to the application;
- the human approves or rejects;
- the agent resumes from saved state.

GBrain-like systems are closer to a team knowledge brain:

- persistent memory backed by a database;
- Markdown pages;
- search;
- links between pages;
- timeline entries;
- tags;
- version history;
- agent tools for storing and querying knowledge.

The practical lesson:

Possible OS should have both file-backed human-legible memory and database-backed
query/update mechanics.

Do not hide the mental model only in embeddings or opaque traces.

## Human Question Capability

The master agent should have a durable `ask_user` capability.

It should be used when the agent needs:

- clarification;
- missing information;
- approval;
- a decision;
- a real-world action;
- credential setup;
- account configuration;
- strategic judgment;
- taste judgment;
- confirmation that something happened outside the machine.

Examples:

- "Should I send the remaining 9 approved lead-gen emails now or wait until
  tomorrow morning?"
- "I need you to enable IMAP in Zoho before I can read incoming replies."
- "Please confirm whether BD&J actually refers clients to Precise Imaging."
- "I found two possible founders. Which one should be treated as the decision
  maker?"
- "This action would change DNS. Please approve before I proceed."

### Data Model

Add a durable table:

```text
agent_questions
```

Suggested fields:

```text
id
status                 pending | answered | dismissed | expired | superseded
question_type          clarification | information | approval | real_world_action | strategic_decision
priority               low | normal | high | urgent
asked_by               master-agent | subagent id
surface                agents | lead-gen | inbox | seo | system
related_goal_id
related_task_id
related_action_id
related_trace_id
question_text
context_json
options_json
recommended_option
blocking               boolean
answer_text
answer_json
answered_by
asked_at
answered_at
expires_at
created_at
updated_at
```

The key distinction is `blocking`.

If `blocking = true`, the related task should move to:

```text
waiting_on_user
```

If `blocking = false`, the agent can continue other work while waiting.

### UI

Add a section in `/agents`:

```text
Questions for Pranav
```

Each question should show:

- the question;
- why the agent is asking;
- what goal it affects;
- what happens if the user does not answer;
- recommended answer;
- buttons or editable response field;
- related trace/action/task links.

For real-world action requests, show:

- requested action;
- step-by-step instructions;
- evidence needed;
- button: "I did this";
- optional evidence text/upload/link.

Example:

```json
{
  "question_type": "real_world_action",
  "question_text": "Enable IMAP for pranav@possiblemindshq.com in Zoho Mail.",
  "why": "The inbox scanner cannot read replies without IMAP.",
  "requested_evidence": "Confirm IMAP is enabled and paste the app password into the secure env flow.",
  "blocking": true
}
```

### Agent Flow

The master agent should handle questions like this:

1. It determines it lacks information or permission.
2. It creates an `agent_questions` row.
3. It creates an operator notification.
4. It marks the related task `waiting_on_user` if blocked.
5. It records a product trace: `agent_question_created`.
6. The user answers in the UI.
7. The answer is saved.
8. The related task is unblocked or resumed.
9. The answer is added to the wake context.
10. If the answer is durable knowledge, it is proposed for the knowledge base.

This is similar to the human-in-the-loop interruption pattern, except Possible
OS should persist the interruption as a durable business object that can survive
minutes, hours, or days.

## Knowledge Base Design

The knowledge base should store the master agent's mental model.

It should not replace traces. Traces are raw evidence. The knowledge base is the
curated interpretation.

Use this distinction:

```text
Traces = what happened.
Reports = what an agent observed.
Findings = what pattern may matter.
Knowledge base = what we believe about the system now.
Skills = how to do repeatable work.
Code = executable implementation.
```

### Recommended Architecture

Use a Markdown-first, database-indexed knowledge base.

Files give human legibility and git diffs.

Database rows give search, tags, status, provenance, and UI management.

Recommended directory:

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
    2026-06-05-human-question-capability.md
  runbooks/
    send-approved-lead-gen-emails.md
    inspect-heartbeat.md
    recover-email-send-failure.md
  open-questions/
    README.md
  glossaries/
    possible-os-terms.md
```

Recommended table:

```text
agent_knowledge_pages
```

Suggested fields:

```text
id
slug
title
kind                   system_model | decision | runbook | goal | glossary | observation | external_reference
path
summary
content_md
tags_json
links_json
source_trace_ids_json
source_action_ids_json
source_report_ids_json
source_urls_json
confidence             low | medium | high
review_status          draft | reviewed | stale | deprecated
owner                  master-agent | operator | subagent
version
supersedes_id
created_by
updated_by
created_at
updated_at
reviewed_at
```

Optional later table:

```text
agent_knowledge_links
```

Fields:

```text
from_page_id
to_page_id
relationship_type      depends_on | contradicts | supersedes | explains | implements | evidence_for
created_at
```

### Memory Layers For Possible OS

Use these layers.

#### 1. Constitutional Memory

Files:

- `soul.md`
- `soul.compact.md`
- prime directives in wake context

Purpose:

Identity, boundaries, taste, first principles.

Rule:

Rarely changes. `soul.md` is protected.

#### 2. Goal Memory

Data:

- `master_goals`
- `docs/agent-kb/goals/current-goal-stack.md`

Purpose:

What the user wants now and over long horizons.

This must include:

- short-term goal;
- medium-term goal;
- long-term goal;
- success metrics;
- current objective status;
- remaining work.

#### 3. System Model Memory

Files:

- `docs/agent-kb/system-model/*.md`

Purpose:

How Possible OS works.

Examples:

- lead-gen loop;
- email send path;
- action approval path;
- trace and learning loop;
- heartbeat context construction;
- subagent lifecycle.

These files are what the master agent should read when it needs to reason about
the system.

#### 4. Episodic Memory

Data:

- `product_traces`;
- `agent_task_events`;
- `agent_reports`;
- `agent_actions`;
- `email_logs`;
- `lead_gen_observations`;
- `inbound_emails`;
- consult bookings.

Purpose:

What happened.

This should be mostly append-only.

Do not put all episodic memory into the prompt. Retrieve summaries and evidence
only when relevant.

#### 5. Procedural Memory

Files:

- `SKILL.md` files;
- runbooks;
- CLI docs;
- validation commands.

Purpose:

How to do repeatable work.

If a process repeats, convert it into a skill or runbook.

#### 6. Semantic Business Memory

Files/tables:

- company facts;
- customer facts;
- PI domain facts;
- product capabilities;
- proof points;
- objections and answers;
- examples of good outreach;
- examples of bad outreach.

Purpose:

What the agent knows about the business and market.

#### 7. Open Questions Memory

Data:

- `agent_questions`;
- `docs/agent-kb/open-questions/`.

Purpose:

What the agent needs from the user or the world.

This prevents unresolved dependencies from disappearing.

## Wake Context Integration

The wake context should include only a compact knowledge bundle.

Do not dump the entire knowledge base into every heartbeat.

Add:

```json
{
  "knowledge_context": {
    "loaded_pages": [
      {
        "slug": "lead-gen-loop",
        "summary": "...",
        "updated_at": "...",
        "confidence": "high"
      }
    ],
    "system_model_summary": {
      "lead_gen": "...",
      "email_send_path": "...",
      "learning_loop": "..."
    },
    "known_gaps": [],
    "stale_pages": []
  },
  "open_questions": [
    {
      "id": "...",
      "question_type": "approval",
      "question_text": "...",
      "blocking": true,
      "related_goal_id": "..."
    }
  ]
}
```

The master agent should answer these on every wake:

1. Do I have enough information and permission to move the user goal forward?
2. If not, what exact question or real-world action request should I create?
3. Does my current system model explain what just happened?
4. If not, what knowledge page should be updated or created?
5. Did new evidence make any existing knowledge stale?

## Update Rules

The knowledge base should not update blindly.

Use these rules:

### Write Immediately

Write immediately when:

- the user states a durable preference;
- the user sets a goal;
- a system architecture decision is made;
- a runbook changes;
- a real-world constraint is discovered.

### Propose For Review

Propose for review when:

- an agent infers a lesson from multiple traces;
- a market feedback pattern appears;
- a lead-gen targeting rule may change;
- a skill should be updated;
- a system model page may be stale.

### Do Not Promote

Do not promote:

- one-off noisy events;
- unverified guesses;
- raw logs;
- credentials;
- sensitive personal data unless explicitly intended;
- long transcripts unless summarized and linked.

## Best First Horizontal Slice

Build this in small complete slices:

### Slice 1: Read-Only Filesystem Capability

1. Add `app/services/filesystem_read.py`.
2. Support structured operations:

```text
list_files
read_file
search_text
git_status
git_diff
git_log
git_show
```

3. Add CLI commands:

```bash
bin/autocaller fs list ...
bin/autocaller fs read ...
bin/autocaller fs search ...
bin/autocaller fs git-status
bin/autocaller fs git-diff
bin/autocaller fs git-log
bin/autocaller fs git-show
```

4. Add the capability registry entry:

```text
read-only filesystem inspection
```

5. Enforce repo-root policy, output limits, and tracing.
6. Verify the heartbeat context can see the new capability.

Implementation note, 2026-06-06:

This slice now exists as a structured read-only service and CLI wrapper:

- `app/services/filesystem_read.py`;
- `bin/autocaller fs list`;
- `bin/autocaller fs read`;
- `bin/autocaller fs search`;
- `bin/autocaller fs git-status`;
- `bin/autocaller fs git-diff`;
- `bin/autocaller fs git-log`;
- `bin/autocaller fs git-show`;
- master-agent capability registry entry:
  `read-only filesystem inspection`.

The capability is deliberately not arbitrary shell. It enforces repo-relative
paths, root containment, sensitive-file blocking, binary-file blocking, output
limits, and product traces. Durable filesystem-read action rows remain deferred
until the bounded runner needs queued read operations.

### Slice 2: Bounded Heartbeat Tool Runner

1. Add `app/services/master_agent_runner.py`.
2. Allow the LLM to request structured `filesystem_read` tool calls.
3. Validate and execute tool calls through the read-only service.
4. Feed tool results back into the next LLM iteration.
5. Stop at iteration, runtime, token, and output limits.
6. Write an agent report or event with continuation state.

### Slice 3: Ask User Capability

1. Add `agent_questions` table.
2. Add backend service:

```python
create_agent_question(...)
answer_agent_question(...)
list_agent_questions(...)
```

3. Add API endpoints:

```text
GET  /api/agents/questions
POST /api/agents/questions
POST /api/agents/questions/{id}/answer
```

4. Add CLI:

```bash
bin/autocaller agents questions
bin/autocaller agents ask-user ...
bin/autocaller agents answer-question ...
```

5. Add `/agents` UI section:

```text
Questions for Pranav
```

6. Add wake context field:

```json
"open_questions": [...]
```

7. If a question is blocking, set related task status to `waiting_on_user`.

### Slice 4: Knowledge Base V1

1. Create `docs/agent-kb/`.
2. Add initial pages:

```text
system-model/possible-os.md
system-model/lead-gen-loop.md
system-model/action-execution.md
system-model/master-agent-heartbeat.md
goals/current-goal-stack.md
```

3. Add `agent_knowledge_pages` table.
4. Add index/sync service that reads Markdown pages into DB.
5. Add search/list endpoints.
6. Add wake context summary with the most relevant system-model pages.
7. Add "propose knowledge update" as an agent finding type.

### Slice 5: Knowledge Maintenance Loop

1. On heartbeat, check if recent evidence contradicts known model.
2. If yes, create a proposed knowledge update.
3. Show it in `/agents`.
4. User approves/rejects.
5. Approved update patches Markdown and syncs DB.
6. Trace the update.

## Architecture And Plan Sync Rule

Keep this architecture file and
`docs/MASTER_AGENT_CONTEXT_IMPLEMENTATION_PLAN.md` in sync.

When a feature is implemented, update both files with a short note:

- what now exists;
- what behavior changed;
- what validation proved it;
- what remains.

The architecture file should explain the conceptual shape. The implementation
plan should explain concrete slices, validation, and current status.

## Design Principle

The question system lets the agent say:

```text
I cannot move safely without you.
```

The knowledge base lets the agent say:

```text
Here is my current understanding of how the system works.
```

Together, they make the master agent less brittle:

- it stops guessing when it should ask;
- it stops forgetting what it learned;
- it can separate raw evidence from durable understanding;
- it can update its mental model over time;
- it can move faster because it knows when it has enough context and when it
  does not.

## Source Notes

- OpenClaw memory docs: Markdown memory, daily notes, optional dreaming, memory
  plugins, and wiki layer.
- Local OpenClaw workspace: `MEMORY.md`, daily `memory/*.md`, `HEARTBEAT.md`,
  `AGENTS.md`, and the explicit "Text > Brain" rule.
- LangGraph memory docs: short-term versus long-term memory, and semantic,
  episodic, and procedural memory types.
- OpenAI Agents SDK human-in-the-loop docs: interruption/approval pattern.
- GBrain/OpenComputer docs: persistent Postgres/vector-backed knowledge base
  with pages, search, versions, graph links, tags, timeline, files, and system
  tools.
