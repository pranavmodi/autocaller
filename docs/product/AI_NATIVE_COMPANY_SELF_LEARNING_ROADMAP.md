# Possible OS: First Self-Learning Loop Roadmap

## Executive Recommendation

Do not begin by building a general “company brain” or granting a master agent broad autonomy.

Begin with one narrow loop that Possible OS can already almost support:

> **Every day, convert operational evidence into one reviewable improvement finding; turn an approved finding into a bounded change; measure whether the change improved a real outcome; preserve the lesson.**

This is the smallest complete step toward an AI-native Possible Minds because it closes the full loop:

```text
observe -> orient -> propose -> review -> act -> verify -> learn
```

The current master-agent foundation already provides heartbeat scheduling, durable goals and tasks, product traces, action events, agent reports, bounded filesystem/action inspection, a sandbox workspace, and approval-gated actions. The missing piece is not another general-purpose agent. It is a reliable mechanism that converts evidence into tested, durable improvements.

## What “AI-Native” Should Mean Here

For Possible Minds, an AI-native company is not one in which everyone uses a chatbot. It is one in which:

1. Important work produces machine-readable evidence.
2. The system can interpret that evidence against explicit objectives.
3. Agents can propose or perform bounded actions through policy-controlled tools.
4. Independent gates evaluate proposed actions before and after execution.
5. Real-world outcomes determine whether a change is kept, reversed, or revised.
6. Accepted lessons update durable plans, knowledge, skills, prompts, evals, or code.
7. Humans concentrate on judgment, relationships, taste, novel situations, and high-risk decisions.

The operating unit is not “an AI employee.” It is a **closed, measurable learning loop**.

## The First Loop: Operational Improvement

### Objective

Make Possible OS improve one observable part of itself every working day without allowing it to make unreviewed high-risk changes.

### Inputs

Use evidence Possible OS already creates:

- `product_traces`;
- master-agent and subagent reports;
- durable action records and policy failures;
- operator approvals, rejections, corrections, and edits;
- todos and task state;
- backend/frontend health checks;
- test and build failures;
- git commits and diffs;
- lead-gen outcomes such as replies, bounces, clicks, bookings, and duplicate-send blocks.

### Output

Each cycle must end in exactly one durable outcome:

- an accepted improvement finding;
- a rejected or duplicate finding with a reason;
- a bounded implementation packet awaiting approval;
- a verified change with measured results;
- a rollback or failed experiment;
- an explicit “no action” decision.

The loop must never end with only a prose status report.

### Initial Success Metric

For the first 30 days, optimize for **learning-loop closure**, not business performance:

```text
closure_rate = findings with a durable disposition / useful evidence clusters reviewed
```

Target:

- Week 1: at least 80% of daily evidence reviews end with a durable disposition.
- Week 2: at least five high-quality findings have cited evidence and a named metric.
- Week 3: at least three approved implementation packets pass their validation gates.
- Week 4: at least one change has a measured real-world outcome and a preserved lesson.

Do not optimize “number of agent actions.” That rewards activity rather than learning.

## Core Data Model

Add a small durable learning ledger instead of placing the entire loop inside heartbeat JSON.

### `improvement_findings`

```text
id
title
domain                    product | lead_gen | reliability | process | knowledge
status                    proposed | needs_review | accepted | rejected |
                          implementing | measuring | validated | reverted
problem_statement
hypothesis
expected_outcome
target_metric
baseline_json
evidence_json              trace ids, report ids, action ids, URLs, file refs
confidence
risk_level
dedupe_key
created_by
reviewed_by
created_at
updated_at
```

### `improvement_experiments`

```text
id
finding_id
change_type                code | prompt | skill | policy | workflow | docs
implementation_ref         packet, branch, commit, action, or config change
validation_plan_json
approval_state
started_at
measurement_window_end
result_json
disposition                keep | revise | revert | inconclusive
lesson
completed_at
```

Every accepted finding must name a target metric and evidence. Every completed experiment must record a disposition and lesson.

## Agent Roles

Keep the roles narrow and adversarial where useful.

### 1. Observer

Collects bounded evidence and groups related signals. It does not propose code changes.

Responsibilities:

- detect new failures, repeated corrections, stale goals, and unexplained outcome changes;
- redact secrets and minimize raw log volume;
- cite exact source records;
- distinguish a new issue from an already-known one.

### 2. Investigator

Turns an evidence cluster into a falsifiable problem statement and hypothesis.

Responsibilities:

- reproduce or confirm the issue through read-only inspection;
- identify the affected objective and metric;
- estimate confidence, risk, and likely blast radius;
- recommend a disposition: no action, gather more evidence, or propose a change.

### 3. Change Proposer

Creates a small implementation packet for an accepted finding.

Responsibilities:

- specify exact scope and non-goals;
- name files or services likely involved;
- define tests, live checks, and rollback conditions;
- work in an isolated branch/worktree;
- never merge, deploy, restart services, or send external messages.

### 4. Evaluator

Acts as the independent quality gate.

Responsibilities:

- check the proposal against policy and product intent;
- run deterministic tests and targeted evals;
- look for regressions, reward hacking, and misleading metrics;
- approve measurement, request revision, or reject.

### 5. Master Agent

Coordinates state transitions; it should not impersonate all four roles in one untraceable prompt.

Responsibilities:

- select the highest-value evidence cluster;
- enforce budgets and stop conditions;
- route work to the correct bounded capability;
- present concise decisions to the operator;
- ensure every cycle receives a durable disposition;
- promote validated lessons into knowledge, skills, prompts, policies, or code.

## Policy Boundaries

### Autonomously Allowed

- read-only inspection of approved data sources;
- evidence clustering and deduplication;
- creation of findings, reports, eval cases, and implementation packets;
- sandbox drafts;
- tests and builds in isolated environments;
- measurement against already-collected outcomes;
- updates to working memory that do not alter production behavior.

### Human Approval Required

- outbound email or calls beyond previously approved exact actions;
- production code merge or deploy during the first 30 days;
- daemon restarts;
- database migrations or destructive data changes;
- credential, billing, DNS, legal, or compliance changes;
- promotion of a proposed lesson into a high-impact policy;
- edits to `soul.md`;
- any action without a tested rollback path.

### Always Logged

- evidence read;
- model decision and model/version;
- tool calls and results;
- policy or quality-gate decision;
- human approval/rejection;
- implementation reference;
- before/after metric;
- final lesson and disposition.

## Concrete 30-Day Roadmap

## Phase 0 — Restore a Trustworthy Heartbeat (Days 1–2)

The current heartbeat is disabled and its last stored run is stale. Repair the control plane before adding autonomy.

Build:

1. Route master-agent LLM calls through `openclaw/proxy` rather than the stateful main OpenClaw agent.
2. Mark expired goals as expired or stale instead of returning them as active.
3. Make heartbeat status reflect runner outcomes; `budget_exhausted` must not appear as an unqualified `ok`.
4. Add freshness fields: `last_completed_at`, `age_seconds`, and `freshness_status`.
5. Reduce wake context to the minimum evidence required for the selected objective.
6. Run three manual heartbeats before enabling a schedule.

Done when:

- three consecutive manual heartbeats finish within budget;
- no stale goal is represented as active;
- status accurately distinguishes success, partial completion, blocked, and budget exhaustion;
- every heartbeat can be reconstructed from traces;
- no production file or external system is changed.

## Phase 1 — Evidence-to-Finding Loop (Days 3–7)

Build the first complete loop without code-writing autonomy.

Build:

1. Add `improvement_findings` and CLI/API/UI parity.
2. Create a daily observer that reads only bounded evidence since the previous successful checkpoint.
3. Cluster duplicate symptoms and link their source trace/report/action IDs.
4. Have the investigator create at most three candidate findings per day.
5. Require each finding to include a problem, hypothesis, target metric, confidence, risk, evidence, and recommended next action.
6. Add a review surface with accept, reject, duplicate, and “needs more evidence.”
7. Require a durable disposition even when the correct answer is no action.

Done when:

- the system produces a useful daily evidence digest;
- every material claim links to source evidence;
- repeated symptoms deduplicate into one finding;
- findings can be reviewed from both CLI and UI;
- the loop produces no code changes or external actions.

## Phase 2 — Finding-to-Implementation Packet (Days 8–14)

Build a proposal loop, still without automatic merge or deploy.

Build:

1. Add `improvement_experiments`.
2. Convert an accepted finding into one bounded task packet.
3. Require an implementation scope, non-goals, validation commands, metric, measurement window, and rollback plan.
4. Run implementation in an isolated worktree.
5. Capture diff, test results, build results, and evaluator feedback.
6. Present a concise approval decision to the operator.

Done when:

- at least three accepted findings produce reviewable packets;
- each packet has exact validation and rollback criteria;
- the evaluator can reject a technically correct change that violates product intent;
- no packet changes the user's dirty working tree;
- nothing merges or deploys automatically.

## Phase 3 — Controlled Experiment and Measurement (Days 15–21)

Close the loop against reality.

Build:

1. Let the operator approve a packet for merge/deploy through an explicit action.
2. Snapshot the target metric before the change.
3. Start a defined measurement window.
4. Compare after-state with baseline and guardrail metrics.
5. Have the evaluator recommend keep, revise, revert, or inconclusive.
6. Require human approval for any rollback that affects live operations.

Choose a low-risk first experiment, such as:

- reducing master-agent heartbeat budget exhaustion;
- improving duplicate action detection;
- improving an internal dashboard or operator workflow;
- correcting a repeatedly failed read-only query.

Do **not** use outbound response rate as the first experiment; it is slow, noisy, and can create customer-facing risk.

Done when:

- one approved change completes a full baseline-to-disposition cycle;
- the result includes both a target metric and guardrail metrics;
- the system can distinguish “no measurable effect” from success;
- rollback remains available and tested.

## Phase 4 — Durable Learning (Days 22–30)

Make successful learning compound.

Build:

1. Promote validated lessons into the correct durable destination:
   - system facts -> knowledge page;
   - repeated procedure -> skill;
   - quality criterion -> eval;
   - operator preference -> reviewed policy or preference record;
   - defect prevention -> test or invariant;
   - strategic choice -> decision log.
2. Preserve provenance from the lesson back to experiment and evidence.
3. Add staleness checks and review dates to learned knowledge.
4. Prevent the same failed experiment from being proposed again without new evidence.
5. Produce a daily report answering:
   - What did the system accomplish?
   - What is blocked?
   - Where is human judgment needed?
   - What did reality teach us?

Done when:

- at least one validated lesson changes a durable system artifact;
- the artifact cites the experiment that justified it;
- a future heartbeat retrieves the lesson when relevant;
- superseded knowledge remains traceable rather than silently overwritten.

## The First End-to-End Demonstration

Use the stale/budget-exhausted master-agent heartbeat as the first dogfood case.

### Evidence

- heartbeat scheduler disabled;
- last run older than two months;
- outer status `ok` while tool loop is `budget_exhausted`;
- runtime exceeded its configured budget;
- expired goal still represented as active;
- status and runner models using the wrong OpenClaw route.

### Hypothesis

If freshness, outcome propagation, model routing, and context size are corrected, manual heartbeats will finish within budget and report trustworthy state.

### Metric

Primary:

```text
successful_heartbeat_rate = heartbeats finishing completed / manual heartbeats run
```

Guardrails:

- runtime under configured limit;
- no false-active expired goals;
- no production mutations;
- no unapproved external actions;
- full trace reconstruction available;
- prompt tokens and cost recorded.

### Test

Run three manual heartbeats over the same bounded diagnostic objective.

### Acceptance

- 3/3 complete within the limit;
- each reports accurate freshness and objective state;
- each produces one durable finding, duplicate disposition, or no-action decision;
- repeated evidence is deduplicated;
- operator can inspect the complete evidence chain.

This demonstration uses the system to improve the system, but keeps the first action internal, measurable, reversible, and low risk.

## Expansion Sequence After the First Loop Works

Only add a new loop when the previous one reliably closes and has a named owner, metric, policy, and rollback path.

Recommended order:

1. **System reliability loop** — errors, slow paths, stale state, test failures.
2. **Operator workflow loop** — repeated manual steps, corrections, and navigation friction.
3. **Lead-generation quality loop** — targeting, evidence quality, draft approval, replies, and bookings.
4. **Knowledge loop** — transcripts and operator decisions update a reviewed, queryable company model.
5. **Delivery loop** — project outcomes, customer feedback, support issues, and reusable implementation patterns.
6. **Strategy loop** — long-term plans and resource allocation, with the founder retaining final judgment.

Each loop should publish events to the same learning ledger so agents can share evidence without becoming an unstructured swarm.

## Anti-Patterns to Avoid

- Building a generic company-brain chat before its sources are trustworthy.
- Treating a generated report as learning without a durable disposition.
- Letting the agent choose its own success metric after seeing results.
- Optimizing proxy metrics such as tool-call count or tokens consumed.
- Giving one model observation, action, evaluation, and approval authority.
- Feeding entire databases, transcripts, or logs into every heartbeat.
- Auto-merging before deterministic tests, evals, rollback, and measurement work.
- Allowing silent knowledge rewrites without provenance or review.
- Creating many specialized agents before one complete loop works.
- Using humans as routine routing middleware instead of reserving them for judgment and risk.

## Immediate Backlog

In priority order:

1. Fix master-agent model routing to `openclaw/proxy`.
2. Fix goal expiry and heartbeat outcome/freshness semantics.
3. Establish three-heartbeat manual reliability baseline.
4. Add the improvement-finding ledger with API, CLI, and review UI.
5. Convert reports and traces into deduplicated, evidence-linked findings.
6. Add explicit no-action and duplicate dispositions.
7. Create the first bounded implementation packet from an accepted finding.
8. Add the independent evaluator gate.
9. Measure one internal, reversible change.
10. Promote the validated lesson into a test, skill, policy, or knowledge page.

## North-Star Test

Possible OS has taken its first meaningful step toward an AI-native company when it can answer “yes” to this question:

> Can the system detect one of its own recurring problems, explain it with evidence, propose a bounded fix, pass an independent review, measure the real result, and preserve the lesson—without relying on a human to route every intermediate step?

Until that loop works reliably, more agents create complexity rather than intelligence.

