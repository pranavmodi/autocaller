# Cybernetic Lead Generation Concept

This document describes the Precise Imaging lead-generation workflow as a
cybernetic function: a closed loop that acts in the market, observes feedback,
updates internal state, and improves future actions against an explicit metric.

## Purpose

The current target metric is booked qualified conversations with personal
injury firms that could benefit from Precise Imaging's records, imaging, or
case-support workflows.

The system is not just an email sender. It is intended to be a control loop:

1. Select the next best firms and contacts under an explicit policy.
2. Execute a human-approved outreach action.
3. Observe reality through delivery events, replies, clicks, bookings, and
   manual notes.
4. Classify that feedback into structured outcomes.
5. Adapt recommendations, suppressions, copy, and routing rules.

Core framing: outbound is the action, feedback is the sensorium, policy is the
memory, and the next batch is the changed behavior.

## Instructions For Future Agents

Treat this document as the living conceptual map for the lead-generation
cybernetic function. When adding, removing, or materially changing a lead-gen
feature, update this file in the same change set.

Required maintenance:

- Update `What Exists Today` when a feature becomes real in code or operations.
- Update `Open Gaps` when a gap is closed, partially closed, or newly exposed.
- Update `Feedback Sources` when a new signal enters the loop.
- Update `Degrees Of Freedom` when the system gains a new way to change its
  behavior.
- Update `When The System Learns` if learning moves earlier, later, becomes
  automated, or becomes human-reviewed.
- Keep deterministic safety actions separate from LLM-mediated interpretation.
- Do not describe aspirational capabilities as implemented. Label them as ideal
  state or open gaps until code, routes, jobs, UI, and verification exist.

## Current Loop

### Policy

The active v1 policy lives in the lead-generation tables and is surfaced by
`GET /api/lead-gen/policy/current`. It currently optimizes for founder, owner,
COO, managing partner, and operations-leader personas while suppressing
contacts that already have communication history, active sequences, unusable
emails, duplicates, or obvious non-law-firm signals.

### Recommendation

`app/services/sequence_recommendations.py` reads the autocaller database and
returns a bounded recommendation batch. The current batch is a records-audit
campaign for firms in the Precise Imaging source data.

### Approval And Execution

`app/services/lead_gen_cybernetic.py` creates batches and starts sequences only
after operator approval. The Lead Gen UI can preview the email for each
individual contact and queue an approved batch over a one-hour window in
California time.

Actual sending still runs through the existing email-sequence scheduler. The
scheduler sends the next due step only when `ALLOW_SEQUENCE_SEND=true`, then
advances sequence state.

### Observation

The system now has three observation paths:

- Manual or API-submitted lead-gen observations through
  `POST /api/lead-gen/observations/classify`.
- Local send logs in `email_logs`, keyed by provider `message_id`.
- Resend webhooks through `POST /api/resend/webhook`, which update
  `email_logs`, create `lead_gen_observations`, and pause/suppress affected
  sequences for delivery failures and complaints.

Resend webhook signing uses the Svix headers `svix-id`, `svix-timestamp`, and
`svix-signature`. Production should set `RESEND_WEBHOOK_SECRET`; unsigned
webhooks are accepted only for loopback/local testing unless explicitly allowed
with `RESEND_WEBHOOK_ALLOW_UNSIGNED=true`.

### Learning

Observed events are stored append-only in `lead_gen_observations`. The current
proposal path can summarize batch outcomes into policy proposals without
automatically applying them. This keeps the learning step inspectable and
human-reviewable.

## What Exists Today

This section is the implementation inventory. Keep it current as the system
evolves.

### Implemented

- **Target metric:** `booked_qualified_conversations`.
- **Policy store:** `lead_gen_policy_versions`, with active v1 policy surfaced
  by `GET /api/lead-gen/policy/current`.
- **Recommendation batches:** `lead_gen_batches` and `lead_gen_batch_items`
  store bounded recommendation sets.
- **Recommendation service:** `app/services/sequence_recommendations.py`
  recommends records-audit contacts from the autocaller database and suppresses
  prior communication history, existing active sequences, unusable emails,
  duplicates, and obvious non-law-firm records.
- **Batch approval gate:** sequences start only after operator approval.
- **Strategy/composer selection:** the Lead Gen UI and API can select a
  strategy template instead of hardcoding copy. The default
  `possible_minds_dynamic` strategy calls the
  `possible-minds-lead-email-composer` skill at send time.
- **Records-audit sequence:** `precise_records_audit`, a three-step records
  workflow audit sequence, remains as a legacy/fallback template.
- **Per-contact preview:** fixed templates can preview exact copy. Dynamic
  strategy steps preview their objective; exact copy is composed from current
  context at send time.
- **California scheduling:** approved batches can be queued with a California
  local start time.
- **One-hour staggering:** batch starts are spread over a one-hour window.
- **Execution gate:** actual sequence sends still require
  `ALLOW_SEQUENCE_SEND=true`.
- **Send logging:** outbound emails write to `email_logs` with Resend
  `message_id`.
- **Observation log:** feedback is stored append-only in
  `lead_gen_observations`.
- **Manual/API observations:** `POST /api/lead-gen/observations/classify`
  accepts feedback events and uses the LLM classifier for semantic feedback.
- **Resend webhook ingestion:** `POST /api/resend/webhook` updates
  `email_logs`, writes deterministic lead-gen observations, and pauses affected
  sequences for delivery risk events.
- **Zoho inbound reply ingestion:** `POST /api/inbound-email/poll` reads the
  Zoho inbox over IMAP, stores normalized inbound messages in `inbound_emails`,
  matches replies by sender email to known firm contacts and lead-gen batch
  items, creates `email_reply` observations, and pauses active matched
  sequences for human/AI review.
- **Operator notifications:** matched lead replies create durable
  `operator_notifications` rows. The Autocaller UI polls
  `GET /api/operator-notifications/pending` and shows a modal with the stimulus
  email, matched firm/contact context, sequence state, classification, and a
  suggested next action/draft response. The operator can edit and send the
  draft as a threaded Resend/SMTP reply via
  `POST /api/operator-notifications/{id}/send-draft`. Acknowledgement/action is
  persisted so the alert does not repeat after refreshes or restarts.
- **Policy proposal path:** `POST /api/lead-gen/batches/{batch_id}/proposal`
  summarizes observed batch outcomes into inspectable proposals without
  automatically applying them.
- **Operator UI:** `/lead-gen` shows policy, templates, recommendation batches,
  contacts, approval state, observations, and learning proposals.
- **Session trace:** `docs/CYBERNETIC_LEAD_GEN_SESSION.md` captures the build
  history, current batch ids, live sends, and operational state from this
  session.

### Partially Implemented

- **Learning:** observations and proposals exist, but policy/copy changes are
  not automatically applied.
- **Suppression:** sequence pausing and item outcomes exist, but there is no
  first-class suppression table for email, contact, firm, domain, or category.
- **Delivery feedback:** Resend webhook code exists, but production still needs
  the deployed webhook URL configured in Resend and `RESEND_WEBHOOK_SECRET`
  stored in the backend environment.
- **Engagement feedback:** opens and clicks can be represented by the Resend
  webhook path, but tracking depends on Resend/domain configuration and email
  format.
- **LLM classification:** the classifier exists for ambiguous feedback, but
  deterministic provider events should not wait on it.

### Not Implemented Yet

- Front/Gmail reply ingestion.
- Cal.com booking, attended, canceled, no-show, and rescheduled feedback into
  lead-gen observations.
- Downstream CRM/deal outcomes.
- First-class suppression records.
- Automated policy version promotion from proposals.
- Automated copy variant generation and experiment assignment.
- Landing-page or booking-link analytics tied back to a specific sequence send.
- Firm-level and domain-level reputation controls.
- Source-of-truth sync from Front as raw comms history.

## What Happens On Delivery Feedback

Provider submission and provider delivery are separate facts. A row can be
`sent` locally because Resend accepted the API request, then later become
`bounced`, `delayed`, `delivered`, `opened`, `clicked`, `failed`, or
`complained` when the webhook arrives.

Current deterministic mapping:

| Resend event | Email log status | Lead-gen outcome | Next action |
| --- | --- | --- | --- |
| `email.delivered` | `delivered` | `neutral` | `no_action` |
| `email.delivery_delayed` | `delayed` | `neutral` | `pause_sequence` |
| `email.bounced` | `bounced` | `bounce` | `suppress_email` |
| `email.failed` | `failed` | `bounce` | `pause_sequence` |
| `email.suppressed` | `suppressed` | `bounce` | `suppress_email` |
| `email.complained` | `complained` | `do_not_contact` | `mark_do_not_contact` |
| `email.opened` | `opened` | `opened_or_clicked` | `continue_sequence` |
| `email.clicked` | `clicked` | `opened_or_clicked` | `continue_sequence` |

## Feedback Sources

The system should learn from every place reality pushes back on its
assumptions.

### Email Delivery Feedback

Source: Resend.

Signals include sent, delivered, delayed, bounced, suppressed, complained,
opened, and clicked. These answer whether the channel is viable, whether the
address is usable, whether the recipient engaged, and whether sender reputation
is at risk.

Current status: delivery feedback ingestion is implemented through
`POST /api/resend/webhook`; production configuration is still required.

### Human Replies

Source: Front, Gmail, Resend inbound, or manual paste.

Signals include positive interest, referral, wrong person, objection, not
interested, do-not-contact, out-of-office, pricing question, vendor question,
already-have-provider, and "send me more information." This is the richest
semantic feedback source because it tells the system what the market actually
understood and what blocked conversion.

Current status: Zoho inbound replies can be polled over IMAP. Matched replies
create observations, pause sequences, and surface operator notification modals
with suggested next actions. Manual/API observations can also record these
events. Front/Gmail are not wired.

### Calendar Feedback

Source: Cal.com or another scheduling system.

Signals include booked, canceled, rescheduled, no-show, attended, qualified,
and unqualified. This connects outreach behavior to the target metric instead
of stopping at opens or replies.

Current status: not normalized into lead-gen observations yet.

### Sales And Operator Notes

Source: human review after replies, calls, meetings, or manual inspection.

Signals include "looked positive but was bad fit," "weak reply became a real
opportunity," "generic inbox worked for this firm type," "founder was wrong
persona," and "COO is the actual buyer." These notes are critical because they
can correct what automated event streams cannot see.

Current status: manual observations can represent these notes, but there is no
dedicated operator-note workflow in the Lead Gen UI yet.

### Autocaller And Comms History

Source: `call_logs`, `email_logs`, `sms_logs`, outreach tables, sequence state,
and firm communications views.

Signals include previous calls, previous emails, SMS, voicemails, duplicate
touches, previous no-answer outcomes, existing active sequences, and recent
firm-level contact. This prevents repetitive or contradictory outreach and
helps select the next best contact.

Current status: recommender already suppresses prior communication history and
existing sequences.

### Firm And Contact Data Quality

Source: Precise Imaging source data, autocaller contacts, Front, manual review,
and enrichment.

Signals include invalid email, stale title, wrong firm, generic inbox, medical
provider misclassified as a law firm, missing founder/COO, wrong state, or
source fields that are repeatedly noisy. This teaches the system which source
records and fields deserve trust.

Current status: basic email usability and non-law-firm filters exist.

### Engagement Behavior

Source: Resend opens/clicks, tracked links, landing pages, booking links, and
future site analytics.

Signals include opens, repeated opens, clicks, booking-page visits, document
views, reply-later behavior, or link engagement by a different person at the
same firm. These are weak signals alone but useful when combined with persona,
firm type, and eventual replies or bookings.

Current status: Resend opens/clicks can enter through the webhook route; richer
web analytics are not wired.

### Deliverability And Reputation

Source: Resend, DNS/domain monitoring, bounce and complaint aggregate rates,
provider throttling, suppression list events, and mail authentication state.

Signals include bounce rate, complaint rate, suppression rate, temporary
failure rate, delivery delay, throttling, and domain health. These should affect
volume, cadence, audience quality gates, and whether a batch pauses.

Current status: per-message delivery risk events can pause sequences; aggregate
batch/domain controls are not implemented.

### Downstream Business Outcomes

Source: CRM, sales notes, meeting outcomes, deal tracking, and invoice/revenue
systems.

Signals include qualified conversation, opportunity created, won deal, lost
deal, deal value, sales-cycle stage, and bad-fit reason. This is the slowest
feedback but the most important, because it distinguishes activity from value.

Current status: not wired.

## When The System Learns

The loop should learn at several speeds.

### Immediate Safety Learning

Trigger: bounce, suppression, complaint, do-not-contact, severe delivery risk,
or obvious bad data.

Action: pause or suppress without waiting for an LLM. These are deterministic
guardrail events.

Current status: Resend bounce, suppression, delay, failure, and complaint
events pause affected sequences. Do-not-contact from replies still requires
reply ingestion or manual observation.

### Per-Event Learning

Trigger: every delivery event, open, click, reply, booking, call summary, or
manual note.

Action: store an append-only observation, classify outcome, update local state,
and choose next action.

Current status: observation storage exists. Resend deterministic events are
handled. Manual/API observations exist. Zoho reply polling exists. Booking
ingestion is not wired.

### Per-Contact Learning

Trigger: a contact produces a meaningful signal or fails as a channel.

Action: continue sequence, pause, suppress email, mark do-not-contact, ask for
referral, find a better contact, or route to a human.

Current status: sequence pause exists; richer next-action execution is still
mostly manual.

### Per-Firm Learning

Trigger: one contact at a firm fails, refers, engages, books, or says the firm
is not a fit.

Action: switch persona, try another contact, pause the firm, route to manual
review, or mark firm-level opportunity state.

Current status: firm-level batch context exists; firm-level suppression and
routing are not implemented.

### Per-Batch Learning

Trigger: enough sends in a batch have produced delivery, engagement, reply, or
booking outcomes.

Action: compare delivery rate, bounce rate, complaint rate, reply quality,
booking rate, persona performance, source quality, and copy performance.

Current status: batch observations and policy proposal endpoint exist; deeper
aggregate dashboards and automatic decision thresholds are not implemented.

### Per-Policy Learning

Trigger: repeated evidence across batches.

Action: propose or apply changes to scoring weights, suppressions, copy,
sequence choice, timing, source trust, or experiment allocation.

Current status: proposals are inspectable and human-reviewed; automatic policy
promotion is not implemented.

## Degrees Of Freedom

These are the levers the system can change as it learns.

### Suppression

Stop contacting an email, contact, firm, domain, persona category, source
category, or segment. Safety suppressions should be immediate for complaints,
do-not-contact requests, hard bounces, and repeated delivery failure.

Current status: sequence pausing and outcome marking exist. First-class
suppression records are still needed.

### Recipient Selection

Change who is selected: founder vs COO, managing partner vs operations leader,
generic inbox vs named person, known Precise contact vs cold contact, or
another person at the same firm.

Current status: v1 policy already weights founder/owner/COO/managing partner
and filters obvious bad records.

### Sequence Selection

Choose a strategy/composer path: dynamic Possible Minds outreach, records-audit
fallback, pain-point fallback, referral ask, reactivation, follow-up from prior
call, or manual-review path.

Current status: UI/API can select strategy templates. New default is
`possible_minds_dynamic`, whose steps are composed by SKILL.md from current
firm context, prior emails/replies, booked consult learnings, Front/Precise
relationship signals, optional blog links, and active policy.

### Copy

Change subject line, opener, offer, proof point, CTA, specificity, tone,
length, objection handling, and whether to reference Precise Imaging directly.

Current status: templates exist, but automated copy learning and variant
assignment are not implemented.

### Timing

Change send time, timezone, weekday, delay between steps, retry window, batch
size, send spread, and stop conditions.

Current status: California start time and one-hour staggering exist.

### Channel

Choose email, call, SMS, manual task, Front reply, calendar invitation, or
multi-channel sequence.

Current status: lead-gen v1 uses email sequences. Calls/SMS exist elsewhere in
the autocaller but are not yet integrated as lead-gen channel choices.

### Routing

Choose who or what handles the next step: continue automation, generate a human
draft, assign a Front task, book directly, ask for referral, or escalate to an
operator.

Current status: observations can record next actions; automated routing beyond
sequence pause is not implemented.

### Scoring Policy

Change weights for persona, firm type, geography, relationship strength, prior
engagement, source reliability, data completeness, and recent communication
history.

Current status: v1 weights exist and policy proposals can be created.

### Data Source Trust

Learn which source fields and systems are reliable. For example, Front may be
the raw truth for conversations, the autocaller DB may be normalized operating
state, and source enrichment may require confidence thresholds.

Current status: source trust is implicit in filters; it is not yet a modeled
policy dimension.

### Experiment Design

Run controlled variants for subject lines, CTAs, personas, send times, sequence
types, and target segments.

Current status: not implemented for lead gen beyond template selection.

## Ideal Loop

The ideal system should make the feedback loop more complete and less
operator-dependent:

1. Front should remain the raw source of truth for contacts and all direct
   human email conversations.
2. The autocaller database should hold normalized operational state: contact
   identity, sequence state, batches, observations, and suppressions.
3. Resend should feed delivery, bounce, complaint, open, and click events into
   the loop automatically.
4. Front or Gmail webhooks should feed actual replies into the loop, including
   referrals, wrong-person signals, do-not-contact requests, and bookings.
5. Cal.com should feed booked, attended, no-show, and canceled meeting events.
6. The LLM should classify ambiguous human language and propose policy/copy
   changes, but deterministic provider events should not wait on an LLM.
7. The system should separate applied policy from proposed policy. Humans
   approve policy/copy changes until the loop has enough evidence to automate
   low-risk adjustments.
8. Every send should be traceable from recommendation reason to rendered copy,
   provider message id, delivery event, reply, outcome, and next action.

Operationally, the ideal loop is:

```text
Recommend -> Approve -> Send -> Observe -> Classify -> Act Immediately Where Safe
-> Aggregate -> Propose Learning -> Human Approves -> New Policy Version -> Next Batch
```

Not every learning should auto-apply. Safety actions can be automatic. Copy,
scoring, segmentation, and policy changes should usually become proposals first,
with human approval, until there is enough evidence to automate low-risk
adjustments.

## Open Gaps

- Zoho reply ingestion exists through IMAP polling and creates operator
  notifications for matched replies, but it is operator-triggered rather than a
  continuous background job.
- Front/Gmail reply ingestion is not wired.
- Resend webhook endpoint is implemented, but the public Resend dashboard still
  needs to point at the deployed backend URL and store the signing secret in
  `RESEND_WEBHOOK_SECRET`.
- Suppression is currently expressed by pausing sequences and marking outcomes;
  a first-class suppression table would make cross-campaign exclusion cleaner.
- The proposal generator summarizes outcomes but does not yet update scoring
  weights or copy variants automatically.
- Bookings are the target metric, but meeting lifecycle events still need to be
  normalized into lead-gen observations.
