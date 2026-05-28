# Cybernetic Lead Generation Session Handoff

Date: 2026-05-26
Workspace: `/home/pranav/autocaller`

This document captures the intent, design decisions, grill-me conclusions,
implementation plan, and code changes from the session that turned the
Precise Imaging lead-generation workflow into a v1 cybernetic function.

## Intent

The goal is not merely to automate email outreach. The goal is to build a
closed-loop lead-generation function that can:

1. Execute outbound actions.
2. Observe feedback from the market.
3. Interpret feedback into structured outcomes.
4. Update memory and recommendations.
5. Improve the next batch under human review.

The primary business metric is:

`number of booked qualified conversations`

Supporting guardrails:

- positive reply rate
- booked conversation rate
- bounce rate
- negative / do-not-contact rate
- duplicate-contact rate
- sequence/persona/source performance

The function should behave like a cybernetic system:

```text
Goal -> Policy -> Action -> Observation -> Interpretation -> Memory -> Policy update
```

The LLM should not silently steer the business. The LLM classifies feedback
and proposes changes. Deterministic software owns selection, approval,
sequence execution, state transitions, and auditability.

## Grill-Me Conclusions

The initial prompt was to get grilled on making the organization
self-learning, AI-legible, and cybernetic.

The concrete function chosen was lead generation using the autocaller email
sequence functionality.

Settled decisions:

- Function: lead generation.
- Target audience: personal injury firms whom Precise Imaging works with.
- Initial channel: email sequences from the autocaller system.
- Primary metric: booked qualified conversations.
- Initial data source: autocaller DB.
- Future source of truth to consider: Front, because it contains raw comms.
- V1 scope: records-only sequence.
- Target persona: founder and/or COO, with managing partners, operations
  leaders, partners, and known decision-maker contacts as fallback.
- Approval gate: records only v1; system recommends next contacts, human
  approves before sequence start.
- Send gate: even after approval, sending remains gated by
  `ALLOW_SEQUENCE_SEND=true`.
- Copy source: the first email in the autocaller email sequences was inspected
  conceptually and the new sequence was based on the records/imaging-status
  workflow rather than a generic AI pitch.

Important product stance:

- Autocaller DB is acceptable for v1 because it already contains contacts,
  comms logs, sequence rows, call logs, SMS logs, and bookings.
- Front should be treated as a future upstream/raw comms source for richer
  reply and thread truth.
- The recommender must check the comms section before recommending contacts.
- Any firm with existing comms history should be suppressed for v1.

## Cybernetic Function Design

The function is modeled as:

```text
Target metric:
  booked qualified conversations

Controller:
  lead-generation policy and recommender

Actuators:
  email sequence runner
  autocaller
  follow-up scheduler

Sensors:
  email_logs
  sms_logs
  call_logs
  booking records
  manual notes
  future Front thread data

Interpreter:
  LLM feedback classifier via OpenClaw gateway

Memory:
  Postgres lead_gen_* tables
  email_sequences
  comms logs
  policy versions
  observations

Learner:
  batch retrospectives and human-reviewed policy proposals
```

Raw feedback is normalized into outcomes:

- `booked_qualified_conversation`
- `positive_reply`
- `referral`
- `wrong_person`
- `not_interested`
- `do_not_contact`
- `bounce`
- `opened_or_clicked`
- `neutral`
- `needs_human_review`

The policy can then learn from:

- which personas produce booked conversations
- which sequence templates work
- which contact sources work
- which firms or inboxes should be suppressed
- which copy variants should be tested

## Implementation Plan That Was Approved

The implementation plan was:

1. Add a shared OpenClaw gateway wrapper.
2. Add persistent lead-generation batch/state tables.
3. Add a feedback classifier skill using the OpenClaw gateway.
4. Add a batch service that creates recommendation batches from the existing
   sequence recommender.
5. Add approval and optional sequence-start flow.
6. Add observation storage and LLM classification.
7. Add human-reviewed policy proposal generation.
8. Expose the loop through API and CLI.
9. Keep all sending gated and avoid autonomous sending.

The OpenClaw gateway pattern was based on the existing blog outreach composer:

- load a `SKILL.md` as the system prompt
- send structured JSON as the user message
- call `OPENCLAW_GATEWAY_URL`
- authenticate from `OPENCLAW_GATEWAY_TOKEN` or
  `/root/.openclaw/openclaw.json`
- parse JSON
- validate required fields
- retry transient gateway failures
- preserve raw LLM output for audit/debugging

## Implementation Completed

### New Sequence Selection System

Sequence rendering and scheduling now use a template registry instead of a
hardcoded sequence.

New files:

- `app/services/sequences/common.py`
- `app/services/sequences/registry.py`
- `app/services/sequences/precise_records_audit.py`

Modified:

- `app/services/sequences/precise_pain_4step.py`
- `app/services/sequence_scheduler.py`
- `app/api/sequences.py`
- `frontend/lib/api.ts`
- `frontend/app/sequences/page.tsx`
- `app/cli.py`

Available templates:

- `precise_pain_4step`
- `precise_records_audit`

The new records audit sequence:

- key: `precise_records_audit`
- variant: `records_only`
- steps: 3
- cadence: day 0, day 5, day 12
- first subject: `Precise Imaging -- quick records question`
- intent: ask whether the firm wants a 20-minute records workflow audit for
  records requests, imaging updates, missing docs, and follow-up loops.

### Recommendation Logic

Added:

- `app/services/sequence_recommendations.py`

The recommender:

- returns one contact per untouched firm
- suppresses firms with comms history in `email_logs`, `sms_logs`, or
  `call_logs`
- suppresses firms with existing sequence rows
- filters unusable emails such as `null` or obfuscated placeholder emails
- suppresses obvious non-law providers from the shared PIF contact table
- dedupes by normalized email address
- prioritizes founder/owner, COO, managing partner, operations leader,
  partner, then known decision-maker contacts

The first recommended approval batch returned 50 contacts, including:

- BH Injury Firm, Shawn Mangoli
- Doyle Accident & Injury Attorneys, James R. Doyle
- Bauman Law, Shaun J. Bauman
- BD&J, Raphael Dara Javid
- Cohen & Marzban, Bob M. Cohen
- Downtown LA Law Group, Farid Yaghoubtil
- Drivers Legal Defense, William H. Dailey
- KR Law, Kathy Rabii
- Pacific Coast Trial Law Firm, Zhiming Wang
- Razavi Law Group, Ali Razavi

No emails were sent.

### Cybernetic Loop Tables

Added migration:

- `alembic/versions/d0e1f2a3b4c5_add_lead_gen_cybernetic_loop.py`

Added models in `app/db/models.py`:

- `LeadGenPolicyVersionRow`
- `LeadGenBatchRow`
- `LeadGenBatchItemRow`
- `LeadGenObservationRow`
- `LeadGenPolicyProposalRow`

Tables created:

- `lead_gen_policy_versions`
- `lead_gen_batches`
- `lead_gen_batch_items`
- `lead_gen_observations`
- `lead_gen_policy_proposals`

The migration was applied locally. `alembic current` showed:

```text
d0e1f2a3b4c5 (head)
```

Postgres verification showed all five `lead_gen_*` tables exist.

### OpenClaw Gateway Client

Added:

- `app/services/llm_gateway.py`

Responsibilities:

- resolve OpenClaw gateway token
- read OpenClaw config from `/root/.openclaw/openclaw.json`
- load and cache `SKILL.md`
- call `/v1/chat/completions`
- parse JSON, including fenced JSON
- validate required fields
- retry transient failures
- return parsed output plus raw response and model

### Feedback Classifier Skill

Added:

- `.claude/skills/lead-feedback-classifier/SKILL.md`
- `app/services/lead_feedback_classifier.py`

The classifier maps raw events into structured outcomes and next actions.

Allowed next actions:

- `confirm_booking`
- `human_reply`
- `ask_for_referral_contact`
- `find_better_contact`
- `continue_sequence`
- `pause_sequence`
- `mark_do_not_contact`
- `suppress_email`
- `no_action`
- `needs_human_review`

Hard rules:

- remove/unsubscribe/stop requests become `do_not_contact`
- hard bounces become `bounce`
- better-person references become `referral`
- opens/clicks alone are weak signals and continue sequence
- ambiguous events become `needs_human_review`

### Lead-Generation Service

Added:

- `app/services/lead_gen_cybernetic.py`

Main service functions:

- `ensure_default_policy`
- `create_recommendation_batch`
- `list_batches`
- `get_batch`
- `approve_batch`
- `classify_and_store_observation`
- `create_policy_proposal_from_batch`

Default active policy:

- version: `lead-gen-v1`
- target metric: `booked_qualified_conversations`
- human approval required
- exclude comms history
- exclude existing sequences
- exclude unusable emails
- dedupe by email

Important behavior:

- `create_recommendation_batch` only writes recommendation rows.
- `approve_batch(..., start_sequences=False)` only approves items.
- `approve_batch(..., start_sequences=True)` creates `email_sequences` rows.
- Actual sending still depends on `ALLOW_SEQUENCE_SEND=true`.

### API

Added:

- `app/api/lead_gen.py`

Registered in:

- `app/api/__init__.py`
- `app/main.py`

Endpoints:

- `GET /api/lead-gen/policy/current`
- `POST /api/lead-gen/batches`
- `GET /api/lead-gen/batches`
- `GET /api/lead-gen/batches/{batch_id}`
- `POST /api/lead-gen/batches/{batch_id}/approve`
- `POST /api/lead-gen/observations/classify`
- `POST /api/lead-gen/batches/{batch_id}/proposal`

### CLI

Added `lead-gen` group in `app/cli.py`:

```bash
bin/autocaller lead-gen policy
bin/autocaller lead-gen recommend --template precise_records_audit --limit 50
bin/autocaller lead-gen batches
bin/autocaller lead-gen show <batch_id>
bin/autocaller lead-gen approve <batch_id>
bin/autocaller lead-gen approve <batch_id> --start-sequences
bin/autocaller lead-gen observe ...
bin/autocaller lead-gen propose <batch_id>
```

Sequence CLI also supports:

```bash
bin/autocaller sequences templates
bin/autocaller sequences recommend --template precise_records_audit --limit 50
bin/autocaller sequences preview <contact_id> --template precise_records_audit
bin/autocaller sequences start <contact_id> --template precise_records_audit
```

## How To Resume

Start in:

```bash
cd /home/pranav/autocaller
```

Check migration:

```bash
set -a && source .env && set +a && .venv/bin/alembic current
```

Expected:

```text
d0e1f2a3b4c5 (head)
```

Check CLI:

```bash
.venv/bin/python -m app.cli lead-gen --help
```

Create a new approval batch:

```bash
bin/autocaller lead-gen recommend --template precise_records_audit --limit 50
```

Show a batch:

```bash
bin/autocaller lead-gen show <batch_id>
```

Approve only, without creating sequence rows:

```bash
bin/autocaller lead-gen approve <batch_id>
```

Approve and create sequence rows:

```bash
bin/autocaller lead-gen approve <batch_id> --start-sequences
```

Sending remains off unless:

```bash
ALLOW_SEQUENCE_SEND=true
```

Classify a manual observation:

```bash
bin/autocaller lead-gen observe \
  --batch <batch_id> \
  --contact <contact_id> \
  --event-type manual_note \
  --text "They replied asking for times next week."
```

Create a human-reviewed policy proposal:

```bash
bin/autocaller lead-gen propose <batch_id>
```

## Verification Already Run

Backend compile:

```bash
.venv/bin/python -m py_compile \
  app/services/llm_gateway.py \
  app/services/lead_feedback_classifier.py \
  app/services/lead_gen_cybernetic.py \
  app/api/lead_gen.py \
  app/db/models.py \
  app/main.py \
  app/cli.py
```

Tests:

```bash
.venv/bin/python -m pytest \
  tests/test_notification_service.py \
  tests/test_lead_gen_cybernetic.py \
  tests/test_sequence_templates.py
```

Result:

```text
22 passed
```

Frontend type check:

```bash
cd frontend && npx tsc --noEmit
```

Result: passed.

App import smoke test:

```bash
.venv/bin/python -c "import app.main; print('ok')"
```

Result:

```text
ok
```

Migration:

```bash
set -a && source .env && set +a && .venv/bin/alembic upgrade head
```

Result: upgraded from `c0d1e2f3a4b5` to `d0e1f2a3b4c5`.

## Important Safety Notes

- No emails were sent during this session.
- No sequence rows were started during the final cybernetic-loop
  implementation unless a future operator runs `lead-gen approve
  --start-sequences`.
- Even after sequence rows exist, the scheduler will not send unless
  `ALLOW_SEQUENCE_SEND=true`.
- LLM classification requires OpenClaw gateway access.
- The classifier stores raw LLM responses for audit.
- Policy proposals are not auto-applied.

## Next Recommended Work

1. Add automatic ingestion from email replies when reply webhooks are available.
2. Add Front sync as the raw source of truth for threaded email replies.
3. Add a batch metrics dashboard:
   - sent
   - replied
   - positive
   - booked
   - bounced
   - do-not-contact
   - persona/source/template breakdown
4. Add policy proposal review/apply UI.
5. Add sequence copy A/B versioning once the first batches produce enough
   feedback.

## Continuation Update: Frontend Operator Surface

After this handoff was first written, the implementation continued with a
frontend operator page for the cybernetic function.

Added:

- `frontend/app/lead-gen/page.tsx`

Modified:

- `frontend/lib/api.ts`
- `frontend/components/Nav.tsx`
- `app/services/lead_gen_cybernetic.py`

New frontend route:

```text
/lead-gen
```

The page provides:

- active lead-generation policy summary
- create recommendation batch form
- sequence-template selection
- batch list with status filter
- batch detail view
- recommended contacts table
- approve-only button
- approve-and-queue-sequences button
- explicit safety reminder that sending still requires
  `ALLOW_SEQUENCE_SEND=true`
- manual feedback observation modal
- OpenClaw-backed observation classification call
- learning proposal trigger

The navigation now includes:

```text
Lead Gen
```

The frontend API client now includes:

- `getLeadGenPolicy`
- `createLeadGenBatch`
- `listLeadGenBatches`
- `getLeadGenBatch`
- `approveLeadGenBatch`
- `classifyLeadGenObservation`
- `createLeadGenProposal`

On 2026-05-27, the live Lead Gen page showed `Policy unavailable` and an empty
sequence-template dropdown because browser-side `/api/*` requests were hitting
the Next.js server on port `3099` instead of the FastAPI backend on port `8099`.
The backend routes were present after restart, but
`http://127.0.0.1:3099/api/lead-gen/policy/current` returned a Next 404.
`frontend/next.config.mjs` now proxies `/api/:path*` and `/audio/:path*` to
`NEXT_PUBLIC_API_URL` or `http://127.0.0.1:8099` by default. The Lead Gen page
also auto-selects the first loaded batch so the detail pane opens directly on
the current recommendations instead of staying on the empty placeholder. The
frontend WebSocket helper also points local browser sessions on
`localhost:3099` or `127.0.0.1:3099` at backend port `8099`, because Next.js
rewrites cannot proxy `ws://` destinations.

A live recommendation batch was created for approval:

- batch id: `63cf846d383b46c0ad6715a5cc84d8bb`
- name: `Precise records audit - next 50`
- template: `precise_records_audit`
- target metric: `booked_qualified_conversations`
- status: `recommended`
- contacts returned: `50`
- approval state: all items pending; no sequences were started

The recommender counts for that batch were:

- contacts seen: `742`
- eligible firms: `113`
- contacted firms suppressed from comms history: `377`
- already sequenced firms: `14`
- suppressed contacted-firm contacts: `492`
- suppressed unusable email: `39`
- suppressed non-law firm: `22`
- suppressed non-persona: `55`
- suppressed duplicate email: `2`

On 2026-05-27, the batch was later approved without queueing sequences:

- status: `approved`
- approved by: `operator`
- approved at: `2026-05-27T08:46:21Z`
- sequence rows attached to batch items: `0`
- records-audit emails scheduled from this batch: `0`

Lead-gen batch queueing now staggers the first email across a 60-minute window
instead of making all rows due immediately. If a 50-contact approved batch is
queued with `start_sequences=true`, the first row is due at queue time and the
last row is due 60 minutes later, with intermediate due times distributed
evenly. The scheduler orders due rows by `next_step_due_at`, so it drains the
batch in due-time order. `ALLOW_SEQUENCE_SEND=true` is still the global send
gate; if that env var is true when the rows become due, emails can send.

Queueing now accepts a California-time schedule. The Lead Gen UI has a
`Start sending (California)` `datetime-local` input. The frontend sends that
naive local time with `scheduled_timezone=America/Los_Angeles`; the backend
converts it to UTC before assigning staggered `next_step_due_at` values. This
means the operator should enter the desired send start as California time, not
as server UTC.

The Lead Gen UI now separates these states:

- `Approve only`: marks recommendations approved without creating sequence rows.
- `Queue approved over 1 hour`: available for an already approved batch that
  has approved items without sequence rows.
- `Approve and queue over 1 hour`: available for a recommended batch.

The recommended contacts table now has a per-row `Preview` action. It renders
the contact-specific next email to send plus the full sequence before queueing
or sending. A static report of the current batch's step-1 previews was also
generated at:

```text
docs/lead_gen_batch_63cf846d_next_email_previews.md
```

After a UI pass, the recommended contacts section no longer uses a horizontally
scrolling table. It renders responsive wrapping rows so `Preview email` is
visible inside the contact cell on desktop and mobile.

During DB smoke testing, creating a one-row lead-gen batch initially exposed
an insert-ordering bug: `lead_gen_batch_items` attempted to insert before the
parent `lead_gen_batches` row. The service now calls `await session.flush()`
after adding the batch and before adding items. A follow-up smoke test created
a one-row batch successfully. The smoke-test batch was then deleted so it does
not clutter the UI.

Additional verification after this continuation:

```bash
npx tsc --noEmit
.venv/bin/python -m py_compile app/services/lead_gen_cybernetic.py app/api/lead_gen.py app/cli.py
.venv/bin/python -m pytest tests/test_notification_service.py tests/test_lead_gen_cybernetic.py tests/test_sequence_templates.py
curl -sS http://127.0.0.1:3099/api/lead-gen/policy/current
curl -sS http://127.0.0.1:3099/api/sequences/templates
curl -sS http://127.0.0.1:3099/api/lead-gen/batches?limit=5
python3 -c "<playwright hydrated browser check for /lead-gen>"
.venv/bin/python -m pytest tests/test_lead_gen_cybernetic.py tests/test_sequence_templates.py
python3 -c "<playwright check for Queue approved over 1 hour and Preview modal>"
```

Result:

```text
22 passed
frontend proxy endpoints returned 200
autocaller-frontend.service active on port 3099
hydrated Lead Gen page showed policy, Precise records audit template,
Precise records audit - next 50 batch, and recommended contacts table
Policy unavailable: false
Create or select a batch placeholder: false
11 targeted lead-gen/sequence tests passed after stagger change
preview modal rendered the subject and body for an individual batch contact
mobile-width browser check: no horizontal overflow, California schedule input
visible, Preview email buttons visible
```

## First Live Send Feedback

A single live test send was executed for the `Precise records audit - next 50`
batch before the scheduled send window:

- Batch id: `63cf846d383b46c0ad6715a5cc84d8bb`
- Batch item id: `fecb4407e37344368cb471031de72664`
- Contact id: `4acf2d9fefd3422aa398dd076b11e5b4`
- Sequence id: `b090ca82aaef4c14aa09bc6494d99fd3`
- Recipient: `info@bhinjuryfirm.com`
- Message id: `cac0af6c-c5f9-4e01-aac3-93617172c177`
- Subject: `Precise Imaging -- quick records question`

Resend accepted the API request, so the scheduler initially advanced the
sequence to step 1 and set the next due time for June 1, 2026. The Resend UI
then reported `Generic Temporary Delivery Failure`, meaning the recipient's
email provider returned a temporary bounce after submission.

Operational action taken:

- Paused the BH Injury Firm `precise_records_audit` sequence so no follow-up
  sends to `info@bhinjuryfirm.com`.
- Recorded the event as a lead-gen observation with
  `event_type=email_bounce`, `classified_outcome=bounce`,
  `confidence=95`, and `next_action=suppress_email`.
- Updated the local `email_logs` row for message id
  `cac0af6c-c5f9-4e01-aac3-93617172c177` from local submission status
  `sent` to delivery-feedback status `bounced`.

Post-action verification showed:

```json
{
  "item_outcomes": {
    "none": 49,
    "bounce": 1
  },
  "sequence_statuses": {
    "active": 49,
    "paused": 1
  },
  "active_first_due": "2026-05-27T16:01:13.469388+00:00",
  "active_last_due": "2026-05-27T17:00:00+00:00",
  "latest_observations": [
    {
      "event_type": "email_bounce",
      "outcome": "bounce",
      "next_action": "suppress_email",
      "confidence": 95,
      "contact_id": "4acf2d9fefd3422aa398dd076b11e5b4"
    }
  ]
}
```

This exposed an important cybernetic-loop gap: Resend delivery webhooks are
not wired into the system yet. The current `email_logs.status` records what was
known at provider submission time unless an operator manually records later
delivery feedback. The next implementation step should be a Resend webhook
endpoint that verifies provider events, matches by `message_id`, updates
`email_logs`, writes `lead_gen_observations`, and automatically pauses or
suppresses affected sequences for bounce and complaint events.

## Resend Webhook Implementation

Added a public Resend webhook endpoint:

```text
POST /api/resend/webhook
```

Implementation files:

- `app/api/resend_webhooks.py`
- `app/services/resend_webhooks.py`
- `tests/test_resend_webhooks.py`

The route is exempted from cookie auth in `app/main.py`, matching the existing
carrier webhook pattern. It verifies Resend's Svix-style signature headers
against the raw request body when `RESEND_WEBHOOK_SECRET` is configured:

- `svix-id`
- `svix-timestamp`
- `svix-signature`

For loopback testing only, unsigned webhook payloads are accepted when no
secret is configured. External unsigned requests fail unless explicitly allowed
with `RESEND_WEBHOOK_ALLOW_UNSIGNED=true`.

Webhook effects:

- Match Resend `data.email_id` to `email_logs.message_id`.
- Update the local email log delivery status.
- Find the matching lead-gen batch item through recipient email, `pif_id`,
  message type, contact, and sequence state.
- Write a deterministic `lead_gen_observations` row for delivery feedback.
- Pause sequences for delayed, bounced, failed, or complained events.
- Mark lead-gen outcomes for bounce, complaint, open, and click signals.

Deterministic mapping:

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

The project-level conceptual overview now lives in
`docs/CYBERNETIC_LEAD_GEN_CONCEPT.md`, and the README identifies lead
generation as a cybernetic function rather than a standalone email sender.

## Zoho Inbound Email Ingestion

Zoho Mail remains the mailbox provider for inbound replies. Added an
operator-triggered IMAP ingestion path:

```text
GET  /api/inbound-email/config
POST /api/inbound-email/poll
GET  /api/inbound-email
```

CLI:

```bash
bin/autocaller inbound status
bin/autocaller inbound poll --limit 20
bin/autocaller inbound poll --limit 20 --classify
bin/autocaller inbound list --matched yes
```

Environment:

```text
ZOHO_IMAP_HOST=imappro.zoho.in
ZOHO_IMAP_PORT=993
ZOHO_IMAP_USER=pranav@possiblemindshq.com
ZOHO_IMAP_PASSWORD=<Zoho app-specific password>
ZOHO_IMAP_MAILBOX=INBOX
ZOHO_IMAP_MARK_SEEN=false
```

The poller reads unread/recent messages without marking them seen by default,
stores normalized messages in `inbound_emails`, matches replies by sender email
to `firm_contacts` and recent lead-gen batch items, writes `email_reply`
observations, and pauses active matched sequences for human/AI review.

## Operator Notifications For Lead Replies

Added a durable operator-notification channel for cybernetic lead-gen feedback:

```text
GET  /api/operator-notifications/pending
POST /api/operator-notifications/{id}/acknowledge
POST /api/operator-notifications/{id}/send-draft
```

Matched inbound lead replies now create `operator_notifications` rows. The
global Autocaller UI polls pending notifications and shows a modal containing:

- the stimulus email subject, sender, excerpt, and received time
- matched firm/contact/batch/sequence context
- the classified outcome, confidence, and next action
- a suggested human-editable reply draft
- an operator-approved send action that sends the draft as a threaded
  Resend/SMTP reply using `In-Reply-To` and `References` from the inbound email

The modal follows the existing consult-booking acknowledgement pattern:
acknowledgement is stored server-side, so the same notification does not repeat
after a refresh or backend restart.

## Dynamic Lead Email Composer

Fixed email copy is now treated as a legacy/fallback path. The default
lead-generation strategy is `possible_minds_dynamic`, whose sequence steps are
objectives rather than fixed emails. At send time, the scheduler calls the
tracked skill:

```text
app/skills/possible-minds-lead-email-composer/SKILL.md
```

The skill composes one plaintext email from current context:

- firm and contact details
- prior outbound emails
- inbound replies
- booked consult patterns from autocaller
- future Front/Precise relationship signals
- inferred pain points
- optional `getpossibleminds.com` blog links
- active policy and safety rules

Every composed email must include the consult URL in the signature:

```text
https://getpossibleminds.com/consult
```

The OpenClaw workspace copy is installed at:

```text
/root/.openclaw/workspace/skills/possible-minds-lead-email-composer/SKILL.md
```

OpenClaw reports the skill as ready. Static templates such as
`precise_records_audit` remain available for fallback/testing, but new lead-gen
batches should default to the dynamic strategy.

## Second Live Send

After the webhook implementation was loaded, one more email was sent from the
same approved batch through the scheduler path:

- Batch id: `63cf846d383b46c0ad6715a5cc84d8bb`
- Batch item id: `f26c86c63036409faee9e9823c20e91d`
- Sequence id: `4aa686ba5f134e45a728eb612cc18cbf`
- Firm: Doyle Accident & Injury Attorneys, APC
- Contact: James R. Doyle, Esq.
- Recipient: `contact@doyleattorneys.com`
- Message id: `ff9c6feb-75f6-4611-999f-14b6474f28ad`
- Subject: `Precise Imaging -- quick records question`
- Message type: `records_audit_step_1`
- Sent at: `2026-05-27T12:01:01.917159+00:00`

Verification after the send:

```json
{
  "sent_item": {
    "firm_name": "Doyle Accident & Injury Attorneys, APC",
    "email": "contact@doyleattorneys.com",
    "sequence_id": "4aa686ba5f134e45a728eb612cc18cbf",
    "current_step": 1,
    "status": "active",
    "last_sent_at": "2026-05-27T12:01:01.930887+00:00",
    "next_step_due_at": "2026-06-01T12:01:01.930917+00:00"
  },
  "batch_sequence_statuses": {
    "active": 49,
    "paused": 1
  },
  "batch_steps": {
    "0": 48,
    "1": 2
  },
  "batch_item_outcomes": {
    "none": 49,
    "bounce": 1
  },
  "observations_count": 1
}
```

## Files Added In This Session

- `.claude/skills/lead-feedback-classifier/SKILL.md`
- `alembic/versions/d0e1f2a3b4c5_add_lead_gen_cybernetic_loop.py`
- `app/api/lead_gen.py`
- `app/services/lead_feedback_classifier.py`
- `app/services/lead_gen_cybernetic.py`
- `app/services/llm_gateway.py`
- `app/services/sequence_recommendations.py`
- `app/services/sequences/common.py`
- `app/services/sequences/precise_records_audit.py`
- `app/services/sequences/registry.py`
- `docs/CYBERNETIC_LEAD_GEN_SESSION.md`
- `docs/CYBERNETIC_LEAD_GEN_CONCEPT.md`
- `frontend/app/lead-gen/page.tsx`
- `tests/test_lead_gen_cybernetic.py`
- `tests/test_resend_webhooks.py`
- `tests/test_sequence_templates.py`

## Files Modified In This Session

- `app/api/__init__.py`
- `app/api/sequences.py`
- `app/cli.py`
- `app/db/models.py`
- `app/main.py`
- `app/services/sequence_scheduler.py`
- `app/services/sequences/__init__.py`
- `app/services/sequences/precise_pain_4step.py`
- `frontend/components/Nav.tsx`
- `frontend/app/sequences/page.tsx`
- `frontend/app/lead-gen/page.tsx`
- `frontend/lib/api.ts`
- `frontend/next.config.mjs`
- `app/api/lead_gen.py`
- `app/api/resend_webhooks.py`
- `app/services/lead_gen_cybernetic.py`
- `app/services/resend_webhooks.py`
- `app/services/sequence_scheduler.py`
- `README.md`
- `tests/test_lead_gen_cybernetic.py`

The repo already had unrelated dirty changes before this session, especially
around outreach and coverage work. Do not assume every dirty file in
`git status` belongs only to this session.
