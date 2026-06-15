# Cybernetic Lead Generation Concept

This is the conceptual design for the Possible Minds lead-generation function.
It explains what the system is, what it optimizes, what it observes, how it
learns, and what it is allowed to change.

Keep this file mostly mutually exclusive from the other lead-gen docs:

- Active implementation backlog: DB-backed todos in the `/todos` UI and
  `bin/possibleos todos ...`.
- Current code/API/schema/operations: `docs/LEAD_GEN_CYBERNETIC_TECHNICAL.md`.
- Historical session handoff: `docs/CYBERNETIC_LEAD_GEN_SESSION.md`.

## Core Idea

Lead generation should operate as a cybernetic function: a closed loop that
acts in the market, observes feedback, updates memory, and changes future
behavior against an explicit objective.

The current objective is:

```text
booked qualified conversations
```

The system should not optimize for raw email volume, raw reply rate, or open
rate by themselves. Those are secondary signals. The primary question is:

```text
Which actions create qualified conversations with firms that Possible Minds can
help?
```

## Control Loop

The loop is:

```text
Sense -> Select -> Compose -> Approve -> Send -> Observe -> Classify
-> Learn -> Propose Change -> Human Approves -> New Policy -> Next Action
```

### Sense

The system gathers available context about firms, contacts, previous
conversations, delivery history, bookings, and operator feedback.

Precise Front is a primary relationship sensor: it can tell us which firm
domains and people have recently interacted with Precise, which inbox workflow
they touched, and whether metadata reveals case-management tooling. Those
signals should improve contact freshness and timing, not copy patient-specific
details into outreach.

### Select

The system decides which limited set of contacts should receive attention
today. Active conversations and due follow-ups should normally consume budget
before new first-touch outreach.

### Compose

The system drafts one email for the selected contact using the current context,
policy, and learning memory.

The first agent-operated slice should be small: select a few senior
decision-makers, gather bounded evidence, compose approval-ready drafts, and
stop before sending. This proves the loop without pretending the system is
ready for fully autonomous daily outreach.

### Approve

A human operator reviews the generated draft, sees the rationale, edits the
copy if needed, and explicitly approves sending.

### Send

The system sends through the configured email channel and stores the trace of
what was sent, why, to whom, and under which policy/version.

### Observe

The system watches for reality pushing back: delivery events, replies,
bookings, rejections, referrals, manual edits, and operator decisions.

### Classify

Feedback is normalized into structured outcomes such as bounce, referral,
positive reply, not interested, do-not-contact, booked qualified conversation,
or wrong-person signal.

### Learn

The system aggregates outcomes against the reasons behind previous choices.
Learning is not just "what happened"; it is "what happened given the policy,
contact, context, email, and rationale that produced the action."

### Propose Change

The system proposes changes to contact selection, copy doctrine, suppressions,
timing, routing, or policy weights. Proposals are inspectable and evidence
backed.

### Human Approves

Humans approve policy/copy/scoring changes until a future policy explicitly
allows narrow, low-risk automation.

## Human And System Responsibilities

The system should own:

- gathering available evidence;
- enforcing deterministic safety gates;
- ranking candidates under explicit policy;
- drafting context-aware emails;
- storing traces;
- normalizing observations;
- aggregating learning signals;
- proposing improvements.

The human operator should own:

- final approval before outbound emails are sent;
- judgment on ambiguous business changes;
- approval of new policy versions;
- approval of skill/prompt changes;
- overrides when the system lacks enough evidence.

The LLM should not silently steer production behavior. It may compose,
classify, summarize, reason over ambiguous evidence, and propose changes. The
applied policy remains explicit.

## Memory Model

The loop needs memory at several levels.

### Contact Memory

What has happened with this person?

Examples:

- prior outreach;
- replies;
- referrals;
- do-not-contact requests;
- bounces;
- role confidence;
- email quality;
- manual edits or rejection history.

### Firm Memory

What has happened with this firm?

Examples:

- best known contact;
- alternate contacts;
- relationship to Precise Imaging;
- operational pain hypotheses;
- active or paused conversation state;
- firm-level suppressions;
- booked or failed consults.

### Segment Memory

What works for a class of firms or people?

Examples:

- founder/owner contacts vs COO contacts;
- direct named emails vs generic inboxes;
- firms with known Precise relationship vs cold firms;
- PI firms vs healthcare providers;
- small firms vs larger firms.

### Policy Memory

What rules govern action?

Examples:

- daily send budget;
- scoring weights;
- suppressions;
- approval requirements;
- safety gates;
- allowed senders;
- automation level.

### Skill Memory

What has the system learned about how to communicate?

Examples:

- copy doctrine;
- winning examples;
- rejected phrases;
- CTA preferences;
- how to mention Possible Minds;
- when to mention Precise Imaging;
- when to ask a question instead of asking for a call.

## Contact Selection Philosophy

Contact selection should answer:

```text
Who should receive attention today, given limited capacity and all known
feedback?
```

The selector should consider:

- active conversations needing response;
- already-generated drafts awaiting approval;
- due follow-ups;
- new first-touch contacts;
- role/persona fit;
- firm fit;
- relationship evidence;
- email quality;
- previous communication history;
- existing sequences;
- delivery risk;
- similarity to booked qualified conversations;
- similarity to failed or suppressed leads.

Contact selection should be deterministic by default. LLMs can help synthesize
ambiguous evidence, but final ranking should be explainable and traceable.

Every selected contact should have a reason trace:

- why this contact;
- why now;
- what policy version;
- what score components;
- what risks;
- what data sources;
- what expected next action.

## Email Composition Philosophy

Email composition should answer:

```text
What is the most useful, context-aware message to send this person now?
```

The composer should receive:

- firm/contact profile;
- previous outbound emails;
- replies;
- firm relationship context;
- booked consult learnings;
- inferred operational pain;
- current policy;
- relevant Possible Minds blog links;
- recent successful and failed examples;
- constraints from the approval/safety layer.

The composer output should include:

- subject;
- body;
- rationale;
- angle;
- CTA;
- evidence used;
- risk flags;
- model/skill version;
- expected next observation.

The email should not feel like a fixed sequence. It should be a single
appropriate next action in an ongoing market conversation.

## Feedback Sources

The system should learn from every place reality pushes back.

### Delivery Feedback

What it tells us:

- whether the address works;
- whether sender/domain reputation is at risk;
- whether the channel is viable;
- whether future sends should pause or suppress.

Signals:

- sent;
- delivered;
- delayed;
- bounced;
- failed;
- suppressed;
- complained;
- opened;
- clicked.

### Human Replies

What it tells us:

- whether the recipient understood the offer;
- whether the pain hypothesis landed;
- whether we reached the right person;
- what objection or need exists;
- whether follow-up should continue.

Signals:

- positive interest;
- referral;
- wrong person;
- pricing question;
- vendor question;
- already-have-provider;
- send-more-info;
- not interested;
- do-not-contact;
- out-of-office;
- booking intent.

### Operator Edits And Decisions

What it tells us:

- where the generated email was weak;
- what language the operator consistently removes;
- what framing the operator adds;
- which drafts are not worth sending;
- which system recommendations are distrusted.

Signals:

- approved unchanged;
- edited lightly;
- edited heavily;
- rejected;
- skipped;
- manually sent;
- manual note.

### Booking Feedback

What it tells us:

- whether the lead became a qualified business conversation;
- whether the previous selection and composition choices produced real value;
- which segments and angles produce useful calls.

Signals:

- booked;
- qualified;
- unqualified;
- attended;
- no-show;
- canceled;
- rescheduled;
- converted to next step.

### CRM And Relationship Feedback

What it tells us:

- whether the firm is already known;
- whether there is an active relationship;
- who at the firm actually owns the workflow;
- whether outreach should be paused, escalated, or routed differently.

Signals:

- Front conversation history;
- Front contact freshness and firm-level activity metadata;
- Precise relationship context;
- CRM status;
- owner assignment;
- deal stage;
- notes from human teams.

## Learning Cadence

Not all learning should happen at the same speed.

### Immediate Safety Learning

Applies quickly when risk is clear.

Examples:

- bounced email;
- complaint;
- do-not-contact request;
- repeated delivery failure;
- clearly wrong firm/contact.

Likely action:

- suppress;
- pause;
- route to human review.

### Daily Tactical Learning

Applies after enough daily feedback exists.

Examples:

- today generated several reply tasks;
- several drafts were heavily edited;
- one contact source produced bad emails;
- a daily send budget was too high or too low.

Likely action:

- summarize;
- propose contact-selection or copy adjustments;
- update tomorrow's action plan after approval.

### Weekly Policy Learning

Applies after a larger pattern emerges.

Examples:

- founder/owner contacts outperform generic inboxes;
- COO replies are rarer but more qualified;
- one angle generates replies but not bookings;
- a source produces stale contacts.

Likely action:

- propose policy weight changes;
- propose suppressions;
- propose skill examples;
- propose experiment variants.

### Long-Term Strategic Learning

Applies across segments and offers.

Examples:

- a market segment is not worth pursuing;
- a new offer is outperforming the original one;
- a blog post consistently improves conversion;
- a different buyer persona is more valuable.

Likely action:

- change targeting strategy;
- change offer framing;
- change content strategy;
- change channel mix.

## Degrees Of Freedom

The system can improve only by changing things it is allowed to change.

### Selection Levers

- which firms to include;
- which firms to suppress;
- which contact/persona to prioritize;
- how to rank direct emails vs generic inboxes;
- how to use relationship signals;
- how much daily budget goes to active conversations vs new starts.

### Composition Levers

- subject style;
- opening line;
- pain hypothesis;
- offer angle;
- CTA;
- specificity level;
- whether to include a blog link;
- how to frame Possible Minds;
- whether and how to mention Precise Imaging.

### Timing Levers

- daily send budget;
- send window;
- follow-up cadence;
- cooldown after replies;
- pause duration after delivery risk;
- retry timing after temporary failures.

### Routing Levers

- continue sequence;
- pause for human review;
- ask for referral;
- find another contact;
- create draft reply;
- suppress;
- book directly;
- escalate to operator.

### Policy Levers

- scoring weights;
- suppression rules;
- safety thresholds;
- approval requirements;
- automation level;
- source trust settings.

## Safety Principles

- Human approval is required before generated outbound emails are sent.
- Provider events with deterministic meaning should not wait for an LLM.
- LLM outputs should be stored with rationale and evidence.
- Policy changes should be proposals before they become active.
- Suppression and safety actions should be conservative.
- Front should remain read-only unless explicitly redesigned otherwise.
- Patient-specific data must never leave through outbound outreach. The egress
  policy gate should block any final rendered email that contains patient
  names, DOBs, medical details, dates of loss, or case-specific patient
  information.
- Every outbound action should be traceable to the policy and context that
  produced it.

## Ideal End State

In the ideal state, the system runs a daily closed loop:

1. Ingest feedback from delivery, inboxes, Front, bookings, CRM, and operator
   decisions.
2. Normalize observations.
3. Update contact, firm, segment, policy, and skill memory.
4. Allocate the daily send budget.
5. Select the best active-conversation and new-start actions.
6. Compose context-aware drafts.
7. Ask the operator to approve, edit, or reject.
8. Send approved emails.
9. Attribute outcomes back to selection and composition decisions.
10. Propose policy, suppression, and skill improvements.
11. Apply approved changes as explicit new versions.

The system becomes self-improving not because it acts autonomously, but because
every action creates evidence, every observation is linked back to the decision
that caused it, and future behavior changes only through auditable policy or
skill updates.
