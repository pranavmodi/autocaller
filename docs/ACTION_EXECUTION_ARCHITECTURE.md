# Possible OS Action Execution Architecture

## Purpose

Possible OS needs a safe way for the master agent and subagents to do real work.

The agent should be able to decide that something should happen, such as sending an approved email, running a health check, creating a Codex task packet, or publishing a drafted article. But the agent should not directly run arbitrary shell commands or mutate production data from free-form LLM text.

The architecture separates three things:

1. Thinking: deciding what should happen.
2. Approval: deciding whether the action is allowed.
3. Execution: doing the action through a narrow, tested adapter.

This keeps Possible OS operationally useful without turning the LLM into an uncontrolled shell.

## Core Principle

The master agent should not execute arbitrary commands.

It should submit typed action requests.

Bad pattern:

```text
LLM says:
Run this shell command:
bin/autocaller email send --to x@example.com --subject "..." --body "..."
```

Good pattern:

```text
LLM says:
Request action:
{
  "type": "send_approved_email",
  "action_id": "act_123"
}
```

Then a policy engine checks whether `act_123` is approved, current, within budget, and safe to execute. Only then does a narrow executor call the existing email service.

## Long-Term Architecture

```text
Master Agent
  observes system state
  decides intent

Action Planner
  converts intent into typed action requests

Action Registry
  defines known action types, schemas, risk levels, and executors

Policy Engine
  checks permission, risk, approval, budgets, and safety rails

Action Queue
  stores requested, pending, approved, running, completed, and failed actions

Executor Workers
  run only known adapters

Trace Ledger
  records proposal, context, approval, execution, and outcome

Outcome Observers
  watch real-world feedback

Learning Loop
  turns repeated corrections and outcomes into improvements
```

## Component Rationale

### Master Agent

The master agent is responsible for orientation and judgment.

It asks:

- What is the current state?
- What goal matters now?
- What work should happen next?
- Which subagent or system capability should handle it?

It should not directly send emails, edit production data, push code, or restart services.

Rationale:

The master agent has broad context and judgment, but broad context is exactly why it should not directly execute high-risk actions. It should choose the action, not bypass the safety system.

### Subagents

Subagents do bounded work.

Examples:

- `SystemsHealthAgent`: read logs, inspect health, report anomalies.
- `ResearchScoutAgent`: find useful articles and summarize learnings.
- Future `LeadGenAgent`: propose lead-gen actions.
- Future `SEOAgent`: propose SEO or agent-discoverability actions.
- Future `CodeMaintenanceAgent`: prepare Codex task packets from traces.

Rationale:

Subagents keep work small and inspectable. They let the master agent delegate without stuffing every detail into one context window.

### Action Planner

The action planner converts a goal into a typed action request.

Example:

```json
{
  "type": "send_approved_email",
  "entity_type": "operator_notification",
  "entity_id": "123",
  "requested_by": "master-agent",
  "reason": "The draft was approved by the operator and is still pending send."
}
```

Rationale:

LLMs are good at deciding intent, but execution needs structure. The planner is the translation layer between natural-language intent and machine-checkable action.

### Action Registry

The action registry defines what actions exist.

Each action type should have:

- name
- description
- input schema
- risk level
- approval requirement
- executor name
- allowed autonomous mode
- rate limits
- rollback or compensation notes

Example:

```json
{
  "name": "send_approved_email",
  "risk_level": "high",
  "requires_human_approval": true,
  "autonomous_allowed": false,
  "input_schema": {
    "notification_id": "integer"
  },
  "executor": "LeadGenEmailExecutor"
}
```

Rationale:

The agent should know what tools exist, but it should not invent execution methods. The registry is the menu of possible actions.

### Policy Engine

The policy engine decides whether an action is allowed.

It checks:

- Is this action type registered?
- Is the payload valid?
- Is the action within the current permission mode?
- Does it require human approval?
- Has approval been granted for this exact version?
- Has the approved content changed since approval?
- Is the daily budget exhausted?
- Is the recipient suppressed or unsubscribed?
- Is the action inside allowed hours?
- Is the target system configured?
- Is the actor allowed to request it?

Rationale:

The policy engine is where safety becomes code. Without it, safety depends on the agent remembering instructions.

### Action Queue

The action queue stores durable state for every action.

Suggested statuses:

```text
proposed
waiting_for_approval
approved
queued
running
succeeded
failed
cancelled
expired
blocked
observed
```

Suggested fields:

- id
- action_type
- status
- risk_level
- requested_by
- approved_by
- approval_id
- entity_type
- entity_id
- input_json
- policy_result_json
- execution_result_json
- error
- trace_id
- created_at
- updated_at
- scheduled_for
- started_at
- completed_at

Rationale:

Actions must survive restarts. A durable queue also lets humans inspect what the system wanted to do, what it did, and why it failed.

### Executors

Executors do the work.

They should be narrow and boring.

Examples:

- `LeadGenEmailExecutor`
- `ZohoInboxObserver`
- `SystemsHealthExecutor`
- `SEOActionExecutor`
- `CodexTaskPacketExecutor`
- `GitExecutor`
- `ServiceRestartExecutor`

An executor should:

- accept a typed action request
- re-check policy before execution
- run one known operation
- write a trace
- return a structured result

Rationale:

Executors should not reason creatively. They should be reliable adapters.

### Trace Ledger

Every action should write traces.

Important trace events:

```text
action_proposed
action_policy_checked
action_waiting_for_approval
action_approved
action_queued
action_started
action_succeeded
action_failed
action_cancelled
action_observed
```

For an email action, traces should capture:

- original draft
- edited draft
- approval metadata
- exact subject/body sent
- recipient
- transport
- result
- later bounce/reply/click/booking

Rationale:

Traces are what make the system learnable. They preserve the story from decision to outcome.

### Outcome Observers

Outcome observers watch what happens after execution.

Examples:

- Zoho inbox scanner sees replies.
- Zoho sent folder confirms sent messages.
- Email webhook sees bounce or delivery event.
- Link tracker sees opens or clicks.
- Consult booking sync sees meetings booked.
- User marks an action done or rejected.

Rationale:

Execution alone is not learning. The system learns when it can connect actions to outcomes.

### Learning Loop

The learning loop groups repeated patterns.

Examples:

- User repeatedly edits email drafts to add a Precise Imaging proof line.
- Emails to generic clinic inboxes bounce more often.
- Founder contacts reply more often than info@ addresses.
- Certain subject lines get replies but no bookings.
- A system health warning keeps recurring after deploys.

The loop should create:

- improvement findings
- eval cases
- Codex task packets
- skill updates
- policy updates

Rationale:

The system should not change itself after one anecdote. It should gather evidence, propose changes, test them, and then apply approved improvements.

## Risk Levels

### Low Risk

Examples:

- read logs
- inspect DB summaries
- generate draft
- create report
- create todo
- create Codex task packet

Usually allowed autonomously.

### Medium Risk

Examples:

- regenerate many drafts
- create many SEO actions
- schedule already approved work
- restart non-critical worker
- update non-production config

May be allowed with constraints.

### High Risk

Examples:

- send email
- make outbound calls
- modify production records
- delete data
- push code
- restart live services
- spend money
- publish public content

Requires explicit human approval in V1.

## Approval Model

Approvals must attach to exact action versions.

For email, approval should include:

- notification id or action id
- recipient
- subject hash
- body hash
- approved subject
- approved body
- approved by
- approved at

If the subject or body changes later, the approval is no longer valid.

Rationale:

Approval should mean "send this exact thing," not "send whatever the system currently has for this contact."

## Execution Policy For Email

The first high-value action type is:

```text
send_approved_lead_gen_draft
```

It should only send when:

- the draft exists
- the user approved the exact draft version
- the recipient is present and valid
- the contact is not suppressed
- the daily send budget allows it
- the action has not already been sent
- Zoho API transport is configured
- the action is inside the allowed send window, unless manually overridden

It should never accept arbitrary body text from the master agent at execution time.

The body should come from the approved draft object.

## CLI Contract

Every action capability needs CLI parity.

Recommended command group:

```text
bin/autocaller actions list
bin/autocaller actions show <action_id>
bin/autocaller actions approve <action_id>
bin/autocaller actions reject <action_id>
bin/autocaller actions execute <action_id>
bin/autocaller actions run-next
bin/autocaller actions policy-check <action_id>
```

For lead-gen email specifically, current V1 command is:

```text
bin/autocaller actions send-approved-lead-gen-draft --item=<batch_item_id> --subject=... --body=...
```

or:

```text
bin/autocaller actions execute <action_id>
```

Rationale:

The CLI is the operator contract for humans, Codex, cron, and the master agent.

## UI Contract

The UI should not be the only execution surface.

It should show:

- proposed actions
- waiting-for-approval actions
- running actions
- completed actions
- failed actions
- why an action is blocked
- policy check details
- trace timeline
- outcome observations

For email, the lead-gen page should remain the execution surface for lead-gen email. The Actions page can point to work, but it should not become the owner of every workflow.

Rationale:

The UI is for visibility and human control. The backend and CLI are the durable execution contract.

## Master Agent Behavior

The master agent should:

1. Wake up.
2. Read compact soul context.
3. Read current goals, tasks, traces, capabilities, and action queue.
4. Decide what needs attention.
5. Create action requests or subagent tasks.
6. Avoid high-risk execution unless policy says it is allowed.
7. Report what it did in human language.

It should not:

- run arbitrary shell commands from LLM output
- send unapproved emails
- change `soul.md`
- delete production data
- hide failed actions
- silently retry risky actions

## Subagent Behavior

Subagents should receive:

- task objective
- bounded context
- allowed tools
- forbidden actions
- expected output schema
- acceptance criteria
- verification commands

They should report back with:

- summary
- key findings
- actions taken
- evidence
- risks
- recommended next actions

Rationale:

The master agent should delegate work in a way that can be inspected and resumed.

## First Horizontal Slice

The first slice should be intentionally narrow:

```text
approved lead-gen email
-> typed action request
-> policy check
-> execute through existing Zoho send path
-> trace result
-> mark source action completed
-> later observe reply/bounce
```

This is a complete working loop.

It proves:

- the agent can request an action
- policy can approve or block it
- executor can perform it
- traces capture the result
- outcomes can attach later
- learning can use the evidence

## V1 Implementation Plan

### Step 1: Add Action Tables

Create durable tables:

```text
agent_actions
agent_action_events
```

`agent_actions` stores the current state.

`agent_action_events` stores the timeline.

Rationale:

The action queue should not be process memory. It must survive restarts.

### Step 2: Add Action Registry

Start with:

```text
send_approved_email
run_systems_health
create_codex_task_packet
```

Only `run_systems_health` can be autonomous initially.

Rationale:

The registry makes the agent aware of what can be done without letting it invent new operations.

### Step 3: Add Policy Checker

Implement:

```text
check_action_policy(action)
```

For `send_approved_email`, block unless:

- approval exists
- content hash matches
- recipient is not suppressed
- action has not already been sent
- transport is configured

Rationale:

Policy checks should be reusable from UI, CLI, API, and worker.

### Step 4: Add Executor Service

Implement:

```text
execute_action(action_id)
```

Dispatch by action type:

```text
send_approved_email -> LeadGenEmailExecutor
run_systems_health -> SystemsHealthExecutor
```

Rationale:

This creates one consistent execution path.

### Step 5: Add CLI

Add:

```text
bin/autocaller actions list
bin/autocaller actions show <id>
bin/autocaller actions policy-check <id>
bin/autocaller actions execute <id>
```

Rationale:

Headless operation and agent operation need the same contract.

### Step 6: Add API

Add:

```text
GET /api/actions
GET /api/actions/{id}
POST /api/actions/{id}/policy-check
POST /api/actions/{id}/execute
```

Rationale:

The UI should use the same backend action system as the CLI.

### Step 7: Connect Lead-Gen Email

When a lead-gen draft is approved, create or update an action:

```text
type: send_approved_email
entity_type: operator_notification
entity_id: notification_id
status: approved
```

Execution calls the existing lead-gen email send path.

Rationale:

This reuses the working email system instead of creating a parallel one.

### Step 8: Add Traces

Write traces for:

```text
action_proposed
action_policy_checked
action_approved
action_started
action_succeeded
action_failed
```

Rationale:

The action system should be AI-legible from day one.

### Step 9: Add UI

Add an Action Execution section showing:

- action type
- status
- policy result
- approval state
- executor result
- trace link

For lead-gen email, execution controls should remain in the lead-gen page.

Rationale:

The user should understand what can run, what is blocked, and why.

### Step 10: Let Master Agent Request Actions

After the action system exists, the master agent can create proposed actions.

For V1, it should not auto-execute high-risk actions.

Rationale:

The master agent becomes operational without becoming unsafe.

## What Exists Today

As of this document:

- The master agent heartbeat exists.
- Compact soul context exists.
- Capability registry exists.
- Adaptive master goals exist.
- `SystemsHealthAgent` exists as a read-only worker.
- Product traces exist.
- Lead-gen email send exists through the lead-gen/operator flow.
- Operator notifications exist.
- The first durable action execution queue exists:
  - `agent_actions`
  - `agent_action_events`
  - `app/services/action_execution.py`
  - `GET /api/actions`
  - `GET /api/actions/{id}`
  - `POST /api/actions/{id}/policy-check`
  - `POST /api/actions/{id}/execute`
  - `POST /api/actions/lead-gen/send-approved-draft`
  - `bin/autocaller actions list`
  - `bin/autocaller actions show`
  - `bin/autocaller actions policy-check`
  - `bin/autocaller actions execute`
  - `bin/autocaller actions send-approved-lead-gen-draft`
- The first action type is `send_approved_lead_gen_draft`.
- The existing lead-gen `/send-draft` endpoint now creates and executes a durable action row, then calls the existing Zoho-backed send path.
- The master agent cannot yet execute arbitrary CLI actions.
- The master agent cannot yet send emails.
  It can only observe this execution system until a future policy-approved master-agent action-request path is added.

## What To Build First

The first smallest working action loop is now implemented:

```text
manual approved lead-gen draft
-> agent action row
-> policy check
-> execute send through existing Zoho path
-> trace result
-> mark action done
```

Next, add:

1. master-agent action proposal
2. autonomous low-risk execution
3. outcome-linked learning
4. higher-risk action types with human approval

## Design Constraints

- Build in horizontal slices.
- Keep high-risk actions human-approved.
- Do not let LLMs run free-form shell commands.
- Make every capability available through the CLI.
- Trace every meaningful decision and execution.
- Keep execution adapters narrow.
- Keep policy reusable.
- Keep action state durable.
- Keep `soul.md` protected.
- Use progressive disclosure for agent context.
- Skillify repeated action procedures.
