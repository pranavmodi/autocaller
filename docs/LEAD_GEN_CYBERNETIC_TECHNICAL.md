# Lead Gen Cybernetic Technical Implementation

This is the engineering map for the Possible Minds lead-generation cybernetic
function. Keep this file focused on what exists, where it lives, how data
moves, and how to operate or test it.

Use the other lead-gen docs for different purposes:

- Conceptual design: `docs/CYBERNETIC_LEAD_GEN_CONCEPT.md`.
- Active backlog: DB-backed `todos` table, exposed through `/todos` and
  `bin/autocaller todos ...`.
- Historical session handoff: `docs/CYBERNETIC_LEAD_GEN_SESSION.md`.

## Runtime Surfaces

### Backend

FastAPI serves the lead-gen APIs through `app/api/lead_gen.py` and related
sensor routes.

Important routes:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/lead-gen/policy/current` | active policy, weights, suppressions, daily send budget |
| `PUT` | `/api/lead-gen/settings/daily-send-budget` | persist daily send budget on active policy |
| `POST` | `/api/lead-gen/batches` | create a daily action plan batch |
| `POST` | `/api/lead-gen/email-agent/slice` | create a no-send 3-contact email-agent slice with research evidence, composer drafts, and durable `send_email mode=lead_gen` actions |
| `GET` | `/api/lead-gen/batches` | list batches |
| `GET` | `/api/lead-gen/batches/{batch_id}` | get batch, items, optional observations |
| `POST` | `/api/lead-gen/batches/{batch_id}/approve` | approve batch and optionally queue sequences |
| `POST` | `/api/lead-gen/batch-items/{batch_item_id}/send-draft` | create and execute a durable `send_email mode=lead_gen` action for the exact edited draft |
| `GET` | `/api/lead-gen/batch-items/{batch_item_id}/draft` | load the current editable draft, preferring the referenced action's subject/body when present |
| `POST` | `/api/lead-gen/batch-items/{batch_item_id}/edit-draft` | save an operator-edited draft, updating an existing live scheduled action or creating a new approved draft action |
| `POST` | `/api/lead-gen/observations/classify` | classify and store manual/API feedback |
| `POST` | `/api/lead-gen/batches/{batch_id}/proposal` | create a human-reviewed learning proposal |
| `GET` | `/api/actions` | list durable Possible OS action execution records; `scheduled=true` returns future scheduled approved sends ordered by `scheduled_for` |
| `GET` | `/api/actions/scheduler/status` | show scheduled-action daemon loop state, last tick, pending scheduled count, and due count |
| `GET` | `/api/actions/{action_id}` | show one action and its event timeline |
| `POST` | `/api/actions/{action_id}/policy-check` | run reusable action policy checks without execution |
| `POST` | `/api/actions/{action_id}/execute` | execute one policy-approved action |
| `POST` | `/api/actions/{action_id}/cancel` | cancel a waiting/approved action and append an event timeline entry |
| `POST` | `/api/actions/{action_id}/reschedule` | move an approved scheduled action to a new future timestamp and append an event |
| `POST` | `/api/actions/lead-gen/execute-approved` | execute already-approved `send_email mode=lead_gen` actions through the policy gate |
| `POST` | `/api/actions/lead-gen/send-approved-draft` | create, and optionally execute, a high-risk approved lead-gen email action |
| `POST` | `/api/inbound-email/poll` | poll Zoho IMAP and create reply observations/actions |
| `GET` | `/api/inbound-email` | list stored inbound messages |
| `GET` | `/api/inbound-email/config` | masked IMAP config |
| `POST` | `/api/resend/webhook` | ingest Resend delivery/engagement events |
| `GET` | `/api/operator-notifications/pending` | pending operator action-center notifications |
| `POST` | `/api/operator-notifications/{id}/acknowledge` | dismiss/action a notification |
| `POST` | `/api/operator-notifications/{id}/send-draft` | send a threaded notification draft |
| `GET` | `/api/todos` | list DB-backed project todos, optionally filtered by area/status |
| `POST` | `/api/todos` | create a DB-backed project todo |
| `PATCH` | `/api/todos/{todo_id}` | edit a DB-backed project todo |
| `DELETE` | `/api/todos/{todo_id}` | delete a DB-backed project todo |
| `GET` | `/api/front/status` | Front sync health, cursors, watermarks, table counts, funnel deltas, and timing feed |
| `GET` | `/api/front/warm-list` | top Front-warm matched firms with named contacts, prior-email flags, and tech signals |
| `GET` | `/api/front/contacts` | synced Front contacts filtered by domain/search |
| `GET` | `/api/front/signals` | tech-stack counts, inbox-activity mix, and suppress-flagged domains |
| `POST` | `/api/front/warm-batch` | create a recommended lead-gen batch directly from selected Front-warm domains |

### CLI

Lead-gen CLI commands live in `app/cli.py` under the `lead-gen` group.

Primary commands:

```bash
bin/autocaller lead-gen policy
bin/autocaller lead-gen recommend --template possible_minds_dynamic --limit 50
bin/autocaller lead-gen email-agent-slice --limit 3 --approval-ready
bin/autocaller lead-gen email-agent-slice --limit 3 --approve-actions --policy-check-first-action --json
bin/autocaller lead-gen batches
bin/autocaller lead-gen show <batch_id> --observations
bin/autocaller lead-gen edit-draft <batch_item_id> --at "10:30 PT"
bin/autocaller lead-gen approve <batch_id>
bin/autocaller lead-gen approve <batch_id> --start-sequences
bin/autocaller lead-gen observe --event-type email_reply --item <batch_item_id> --text "..."
bin/autocaller lead-gen observations --since 7d
bin/autocaller lead-gen observations --since 7d --type email_sent --contact <contact_id>
bin/autocaller lead-gen observations summary --since 7d
bin/autocaller lead-gen propose <batch_id>
bin/autocaller front sync --max-calls 300
bin/autocaller front status
bin/autocaller front contacts --domain examplelaw.com
bin/autocaller front warm-batch --domains examplelaw.com,anotherfirm.com
bin/autocaller leads warm-list --limit 20
bin/autocaller actions list --type send_approved_lead_gen_draft
bin/autocaller actions list --scheduled
bin/autocaller actions scheduler-status
bin/autocaller actions show <action_id>
bin/autocaller actions policy-check <action_id>
bin/autocaller actions execute <action_id>
bin/autocaller actions cancel <action_id> --reason "operator changed plan"
bin/autocaller actions reschedule <action_id> --at "11:00 PT"
bin/autocaller actions execute-approved-lead-gen --limit 1 --actor master-agent
bin/autocaller actions send-approved-lead-gen-draft --item <batch_item_id> --subject "..." --body "..." --at "09:30 PT"
bin/autocaller actions send-email --mode lead_gen --to <email> --subject "..." --body "..." --contact <contact_id> --item <batch_item_id> --at "2026-06-11T09:30:00-07:00"
bin/autocaller listening brief
bin/autocaller listening search "medical records follow up" --limit 8
bin/autocaller listening prep "<firm-or-name>"
bin/autocaller inbound poll --limit 50 --classify
bin/autocaller todos list --area lead-gen
bin/autocaller todos add "Review new workflow idea" --area lead-gen --source-url https://...
bin/autocaller todos update <id> --status done
bin/autocaller todos delete <id>
```

The CLI reference remains in `docs/cli.md`.

### Front Read-Only Lead Engine

Files:

- Schema: `app/db/models.py` (`FrontContactRow`, `FrontFirmActivityRow`,
  `FrontSyncStateRow`) and Alembic revision
  `n6o7p8q9r0s1_add_front_lead_engine.py`.
- Service: `app/services/front_sync.py`.
- API: `app/api/front.py` exposes `/api/front/status`, `/api/front/warm-list`,
  `/api/front/contacts`, `/api/front/signals`, and `/api/front/warm-batch`.
- CLI: `front sync`, `front status`, `front contacts`, `front warm-batch`, and
  `leads warm-list`.
- Frontend: `frontend/app/front/page.tsx` renders sync health, funnel counts,
  the expandable warm-list table, timing feed, and signals panel.

Tables:

- `front_contacts`: one row per Front contact, keyed by `front_id`, with
  handles, primary email, domain, Front update time, first sync time, and raw
  contact JSON.
- `front_firm_activity`: domain-level metadata aggregate only. It stores
  contact count, last seen/referral/records timestamps, inbox breakdown, tech
  signals, matched `pif_id`, and `warm_score`.
- `front_sync_state`: per-stage cursor and watermark.
- `firm_contacts` now has nullable `front_contact_id`, `front_last_seen`, and
  `tech_signals` columns.

Operational constraints implemented:

- Front credentials load from
  `/root/.openclaw/workspace/secrets/front_precise.env` via dotenv.
- API stages are read-only GETs.
- `FrontRateBudget` hard-caps calls per run and enforces at least 1.5 seconds
  between calls.
- Contacts sync paginates `/contacts`, persists cursor/watermark after each
  page, and derives the domain from the primary email handle.
- Inbox activity sync reads selected inbox conversation metadata only and never
  stores message bodies.
- Firm resolution is offline. It reads Mission Control SQLite in read-only
  mode, matches domains to `pif_firms.website` and `pif_firms.emails`, skips
  consumer domains, excludes `*.filevineapp.com` robot contacts, and records
  Filevine as `tech_signals.case_mgmt = "filevine"`.
- Warm scoring is offline and writes `front_firm_activity.warm_score`.
- `/api/front/warm-batch` and `front warm-batch` never call Front. They validate
  selected domains against synced rows, pick eligible named contacts that have
  not already been emailed, create a normal `lead_gen_batches` row, and add
  pending `lead_gen_batch_items` with `reason_json.basis = "front-warm"` plus
  score breakdown and source features.

Policy integration:

- `refresh_warm_scores()` creates `lead-gen-v2` if absent and leaves it
  inactive.
- `lead-gen-v2` is a v1-style deterministic policy with
  `front_warmth.weight` and `front_warmth.max_bonus`.
- Contact selection reads `front_warm_score` only when the active policy has a
  Front warmth weight, so v1 behavior remains unchanged.

### Auto-Observation Contract

All meaningful lead-generation feedback enters `lead_gen_observations`
automatically through `app/services/lead_gen_cybernetic.py::record_observation`.
The helper accepts:

```python
record_observation(event_type, raw_event, *, contact_id=None, batch_id=None,
                   batch_item_id=None, classification=None)
```

It enriches linkage from `batch_item_id` or `contact_id` when possible, stores
the raw event payload, and writes a stable `dedupe_key`. Repeating the same
`(event_type, dedupe_key)` returns the existing observation instead of creating
a duplicate. Deterministic events pass deterministic classifications and never
call an LLM. Genuine inbound replies are the only automatic event type that
uses the existing lead feedback classifier.

Current event taxonomy:

| event_type | Source | Classification |
| --- | --- | --- |
| `email_sent` | successful `send_email mode=lead_gen` or approved lead-gen draft execution, including scheduled daemon execution | deterministic neutral / continue sequence |
| `email_send_failed` | transport exception or policy refusal in `execute_action` | deterministic failure / pause sequence |
| `email_reply_received` | Zoho inbound reply matched to a lead-gen contact/batch item | existing LLM feedback classifier |
| `link_clicked` | tracked `link_events` click attributed to an outreach send | deterministic opened-or-clicked |
| `consult_booked` | website consult booking or Cal.com booking made during a call | deterministic booked qualified conversation |
| `call_disposition` | judge persistence after outbound call review finalizes GTM disposition | deterministic mapping from GTM disposition |
| `email_action_cancelled` | approved/waiting lead-gen email action cancellation | deterministic audit trail |
| `email_rescheduled` | scheduled lead-gen email action moved to a new time | deterministic audit trail |

The weekly learning KPI is:

```bash
bin/autocaller lead-gen observations summary --since 7d
```

### Frontend

The lead-gen operator UI is `frontend/app/lead-gen/page.tsx`. The editable
project backlog is a separate page at `frontend/app/todos/page.tsx`; it has its
own nav entry and syncs directly with the `todos` table through `/api/todos`.

It currently supports:

- active policy display;
- daily send budget editing and saving;
- generating today's action plan;
- batch approval and one-hour queueing;
- California-time scheduling;
- per-contact generated preview;
- editable draft send;
- manual observation entry;
- proposal generation;
- row-level score component visibility.
- creating a 3-contact approval-ready email-agent slice;
- opening stored `agent_draft` drafts directly in the Lead Gen modal;
- sending approved modal drafts through durable `send_email mode=lead_gen`.

Global operator actions are in
`frontend/components/OperatorNotificationPopup.tsx`. Despite the legacy file
name, it is now a non-blocking action center with:

- floating pending-action count;
- dismissible toast;
- side drawer;
- pending action list;
- stimulus and lead context;
- rationale;
- editable draft;
- acknowledge and send actions.

Frontend API bindings live in `frontend/lib/api.ts`.

## Core Backend Services

### Policy And Batch Control

File: `app/services/lead_gen_cybernetic.py`

Responsibilities:

- ensure and backfill the active default policy;
- read and update daily send budget;
- create recommendation/action batches;
- serialize batches, items, observations, and proposals;
- approve batches;
- schedule queueable sequence starts;
- send and edit batch-item drafts through the durable action execution slice;
- classify and store observations;
- create learning proposals.

### Durable Action Execution

File: `app/services/action_execution.py`

Durable action execution wraps test email and lead-gen email sending.

Current email action modes:

- `send_email mode=test`
- `send_email mode=lead_gen`
- legacy `send_approved_lead_gen_draft`

For `send_email mode=lead_gen`, the action input includes the exact approved
recipient, subject, body, contact id, batch item id, firm metadata, composer
variant metadata, nullable listening `brief_version`, and subject/body hashes.
Both `send_email` and legacy `send_approved_lead_gen_draft` can also store
`agent_actions.scheduled_for` when the operator uses `--at`; the action remains
`approved`, is policy-checked immediately, and is not sent until the daemon
scheduled-action loop finds it due.
Operators can cancel or reschedule approved scheduled actions through
`actions cancel` and `actions reschedule`; both append action events.
`lead-gen edit-draft` loads `reason_json.agent_draft` but prefers the current
action input when `send_email_action_id` points at an action. Saving updates a
live approved scheduled action in place, including approval hashes and optional
`scheduled_for`, instead of creating a duplicate. If no live scheduled action
exists, it creates a new approved `send_approved_lead_gen_draft` action. The
same service helper syncs `reason_json.agent_draft`, `send_email_action_id`,
scheduled PT/UTC display fields, `operator_edited=true`, and
`approval_status=approved`.

Policy checks verify:

- action status allows execution;
- human approval metadata exists;
- recipient matches the approval;
- subject/body hashes match the approved copy;
- recipient is valid;
- contact exists;
- contact email matches the recipient;
- batch item exists;
- batch item is not already started;
- selection suppressions are empty;
- consult link is present in the body;
- Zoho API transport is configured;
- active daily budget is readable and greater than zero;
- no prior successful `lead_gen` action exists for the same batch item;
- no prior successful `lead_gen` action exists for the same recipient.

Execution sends through `_send_email(..., transport="zoho_api")`, then writes
send metadata back onto both the durable action result and
`lead_gen_batch_items.reason_json`.

The durable action result includes:

- `sent_to`;
- `sent_subject`;
- `sent_message_id`;
- `sent_at`;
- `message_type`;
- `transport`;
- `email_log_id`;
- `email_log_status`;
- an `email_log` snapshot with recipient, subject, message type, transport,
  provider message id, status, error, and timestamp.

The lead-gen batch item reason JSON includes:

- `last_sent_at`;
- `last_sent_message_id`;
- `last_sent_email_log_id`;
- `last_sent_subject`;
- `last_sent_mode = lead_gen`;
- `last_sent_transport`;
- `last_sent_status`;
- composer skill metadata when present.

Heartbeat includes compact recent action summaries in its wake context so the
master agent can see whether recent durable sends actually linked to an email
log row and transport result.

Scheduled sends:

- CLI accepts ISO-8601 with offset or `HH:MM PT|PDT|PST` for today in
  America/Los_Angeles.
- `actions send-email --at ...` and `actions send-approved-lead-gen-draft --at ...`
  create approved scheduled actions, run policy check, and do not execute.
- `app/services/action_scheduler.py` runs from the FastAPI lifespan every 30
  seconds, selecting approved rows where `scheduled_for <= now()`, oldest first.
- Each due action is executed through `execute_action`, so all normal policy
  checks run again at send time.
- Rows more than 24 hours stale are marked `expired` with an error note instead
  of sending.
- `/actions` shows future scheduled actions with Pacific time, relative timing,
  and stored subject/body from `input_json`.

The master agent can send lead-gen email only through
`execute_approved_lead_gen_email_actions`. That function drains existing
`agent_actions` rows where:

- `action_type = send_email`;
- `input_json.mode = lead_gen`;
- `entity_type = lead_gen_email`;
- `status = approved`.

Each candidate still runs through `execute_action`, which re-checks policy
before any email leaves the system. The master agent cannot create recipients,
modify drafts, or bypass approval hashes in this path.

Heartbeat uses this executor only when
`agent_config.auto_execute_approved_lead_gen_email_enabled` is true. The per-run
limit is `agent_config.auto_execute_approved_lead_gen_email_limit`, clamped to
1-25. The same settings are exposed by:

```bash
bin/autocaller agents config \
  --auto-send-approved-lead-gen \
  --auto-send-limit 1
```

### Email-Agent Slice

File: `app/services/lead_gen_email_agent.py`

This is the first horizontal slice for the master agent to create lead-gen email
work without sending email.

Flow:

1. `create_lead_gen_email_agent_slice(limit=3)` creates a normal lead-gen
   recommendation batch.
2. Contact selection reuses the deterministic recommender and only targets
   founders, CEOs, COOs, managing partners, partners, operations leaders, or
   equivalent senior operators.
3. `research_contact_context` creates a bounded internal evidence packet from:
   - `firm_contacts` name/title/email/source/LinkedIn;
   - `patients` firm website/state/metadata where available;
   - email quality;
   - selection reason, score, features, and suppressions.
4. `compose_lead_email` calls
   `app/skills/possible-minds-lead-email-composer/SKILL.md` through the
   OpenClaw gateway with contact, firm, history, research, selection evidence,
   policy, proof points, consult-signature constraints, and, when Mission
   Control is reachable, latest listening brief context plus top matched
   insights.
5. The generated subject, body, rationale, angle, CTA, risk flags, composer
   variant, skill path, skill hash, and nullable `brief_version` are stored in
   `lead_gen_batch_items.reason_json.agent_draft`.
6. A durable `send_email mode=lead_gen` action is created for each draft.
   Default status is `waiting_for_approval`; `--approve-actions` creates exact
   approved no-send actions useful for policy-check validation.
7. A `lead_gen_email_agent_slice_created` product trace records the batch,
   draft count, action ids, and optional first policy-check result.

The route and CLI intentionally do not execute email sends.

Legacy action type:

- `send_approved_lead_gen_draft`

Execution flow:

1. The operator approves an exact subject/body in the lead-gen draft modal or CLI.
2. The backend creates an `agent_actions` row with:
   - `action_type = send_approved_lead_gen_draft`
   - `risk_level = high`
   - `entity_type = lead_gen_batch_item`
   - `entity_id = <batch_item_id>`
   - subject/body hashes in `input_json`
   - approval metadata in `input_json.approval`
3. The policy checker verifies:
   - action status allows execution;
   - approval metadata exists;
   - subject/body are present;
   - subject/body hashes match the approved version;
   - the rendered subject/body pass `no_patient_data_in_outreach`;
   - Zoho API transport is configured;
   - the batch item exists;
   - the batch item has not already started;
   - the contact has an email address;
   - no prior successful action exists for the same batch item.
4. If allowed, the executor marks the action `running`.
5. The executor calls `send_batch_item_draft`, preserving the existing Zoho-backed send behavior.
6. The executor marks the action `succeeded` or `failed`.
7. `agent_action_events` and `product_traces` record approval, policy check, start, success, or failure.

The master agent does not yet create or execute this high-risk action by itself.
That requires a future policy-approved action-request path.

Important constants:

- `TARGET_METRIC = "booked_qualified_conversations"`
- `DEFAULT_POLICY_VERSION = "lead-gen-v1"`
- `DEFAULT_BATCH_STAGGER_MINUTES = 60`
- `DEFAULT_DAILY_SEND_BUDGET = 50`

### Daily Action Planner

File: `app/services/lead_gen_action_planner.py`

Responsibilities:

- allocate the daily budget across existing conversations and new starts;
- prioritize pending inbound reply notifications;
- prioritize already-composed draft approval notifications;
- include due follow-up sequences;
- fill remaining capacity with scored new first-touch contacts;
- dedupe by contact and email;
- return explainable `LeadGenActionCandidate` rows.

Action types:

- `reply_to_inbound`
- `approve_existing_draft`
- `follow_up`
- `first_touch`

Queueable actions:

- `first_touch`
- `follow_up`

Continuation actions that use the action center:

- `reply_to_inbound`
- `approve_existing_draft`
- `follow_up`

### New-Contact Recommendations

File: `app/services/sequence_recommendations.py`

Responsibilities:

- read candidate contacts from `firm_contacts`;
- enrich firm name/state from `patients`;
- suppress firms with prior call/email/SMS history;
- suppress firms with existing email sequences;
- suppress unusable emails;
- suppress obvious non-law-firm records;
- select the best contact per firm;
- dedupe by email;
- return ranked new-start candidates.

Primary source tables:

- `firm_contacts`
- `patients`
- `email_logs`
- `sms_logs`
- `call_logs`
- `email_sequences`

### Contact-Selection Scoring

File: `app/services/contact_selection.py`

Responsibilities:

- compute deterministic explainable scores for new-start contacts;
- merge active policy weights with defaults;
- classify persona;
- classify email quality;
- classify firm-fit signals;
- detect non-law-firm records;
- return score breakdown, features, signals, suppressions, and reason text.

Current score dimensions:

- `persona`
- `firm_fit`
- `relationship`
- `email_quality`
- `history`
- `risk`

Stored selection trace on `lead_gen_batch_items.reason_json`:

- `score_breakdown`
- `selection_features`
- `selection_policy_version`
- `suppressions`
- `signals`
- `reason`

### Dynamic Email Composer

File: `app/services/lead_email_composer.py`

Skill:

- `app/skills/possible-minds-lead-email-composer/SKILL.md`

Responsibilities:

- build the evidence packet for one email from firm/contact data, DB email logs,
  stored inbound replies, booked consult patterns, and direct Zoho Sent mailbox
  lookup for prior messages to the recipient;
- fetch the latest Mission Control listening brief and top five matched
  insights from `app/services/listening_client.py`; failures are soft and leave
  `brief_version` null;
- call the local skill/LLM path;
- produce subject, body, rationale, angle, CTA, blog link, model, and risk
  metadata including nullable `brief_version`;
- keep the email plaintext, remove disallowed dash punctuation, and require
  human review.

The skill payload intentionally does not include sequence/template internals.
It receives `conversation_state` plus real conversation history, including
`history.previous_emails`, `history.zoho_sent_emails`,
`history.zoho_sent_lookup`, and `history.replies`.

### Sequence Scheduling

Files:

- `app/services/sequence_scheduler.py`
- `app/services/sequences/possible_minds_dynamic.py`
- `app/services/sequences/registry.py`

Responsibilities:

- start sequence rows;
- render or compose due steps;
- create operator approval notifications for dynamic generated outbound emails;
- send only when allowed by execution gates;
- advance sequence state and cadence.

Execution gate:

- Actual scheduled sequence sending still requires `ALLOW_SEQUENCE_SEND=true`.

### Inbound Email Sensor

File: `app/services/inbound_email.py`

Responsibilities:

- read Zoho IMAP;
- store normalized inbound email rows;
- match inbound replies to firm contacts, sequences, and batch items;
- optionally classify replies;
- create lead-gen observations;
- pause matched active sequences;
- create operator notifications with suggested next action/draft.

### Delivery Sensor

File: `app/services/resend_webhooks.py`

Responsibilities:

- verify Resend webhook signatures when configured;
- update `email_logs`;
- create lead-gen observations from deterministic provider events;
- pause affected sequences for delivery risk.

Resend event mapping:

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

### Feedback Classifier

File: `app/services/lead_feedback_classifier.py`

Responsibilities:

- classify ambiguous feedback into structured outcomes;
- return confidence, reasoning, and proposed next action;
- use deterministic outcomes for provider events where no LLM is needed.

### Operator Notifications

Files:

- `app/api/operator_notifications.py`
- `app/services/operator_notifications.py`
- `frontend/components/OperatorNotificationPopup.tsx`

Responsibilities:

- persist pending operator actions;
- show global action-center notifications;
- send threaded replies or approved outbound drafts;
- acknowledge/action notifications so they do not repeat after refresh.

## Database Tables

Lead-gen policy and planning:

- `lead_gen_policy_versions`
- `lead_gen_batches`
- `lead_gen_batch_items`
- `lead_gen_observations`
- `lead_gen_policy_proposals`

Email execution and feedback:

- `email_sequences`
- `email_logs`
- `inbound_emails`
- `operator_notifications`

Contact and firm context:

- `firm_contacts`
- `patients`
- `call_logs`
- `sms_logs`

Important stored JSON fields:

- `lead_gen_policy_versions.weights_json`
- `lead_gen_policy_versions.suppressions_json`
- `lead_gen_batches.counts_json`
- `lead_gen_batch_items.reason_json`
- `lead_gen_observations.raw_event_json`
- `lead_gen_policy_proposals.proposed_change_json`
- `lead_gen_policy_proposals.evidence_json`
- `operator_notifications.stimulus_json`
- `operator_notifications.context_json`
- `operator_notifications.suggested_action_json`

## Data Flow

### Generate Today's List

1. Operator opens `/lead-gen`.
2. UI loads `GET /api/lead-gen/policy/current`.
3. Operator saves daily budget if needed.
4. Operator clicks generate today's list.
5. UI calls `POST /api/lead-gen/batches`.
6. Backend calls `plan_daily_lead_gen_actions`.
7. Planner ranks active conversation actions first.
8. Planner fills remaining budget from `recommend_sequence_contacts`.
9. New contacts are scored by `score_contact_selection`.
10. Batch and item rows are stored.
11. UI shows selected actions, reasons, scores, and score components.

### Approve And Queue

1. Operator approves a batch.
2. UI calls `POST /api/lead-gen/batches/{batch_id}/approve`.
3. If `start_sequences=false`, items are only approved.
4. If `start_sequences=true`, queueable items start or update sequences.
5. Each queued sequence immediately creates a lightweight operator action
   notification and pauses as `awaiting_operator_send_approval`.
6. Draft composition is lazy: the action center composes the email only when the
   operator opens that notification.
7. Actual sending remains manual: the operator must edit/review and click send
   from the action center.

### Compose And Approve Email

1. An opened action-center item or due dynamic sequence step requests a composed
   draft.
2. Backend builds the context packet.
3. Composer skill returns subject, body, rationale, angle, CTA, and metadata.
4. Backend creates an operator notification.
5. Sequence pauses as awaiting operator send approval.
6. Operator edits and sends from the action center.
7. Backend sends through configured email transport and advances sequence.

### Observe Replies

1. Zoho poll reads inbound messages.
2. New messages are stored in `inbound_emails`.
3. Matching logic links the message to a contact/sequence/batch item when
   possible.
4. The system creates `lead_gen_observations`.
5. Matched active sequences pause.
6. Operator action-center items are created for review/reply.

### Observe Delivery Events

1. Resend posts webhook event.
2. Backend validates signature when configured.
3. `email_logs` status updates.
4. Deterministic lead-gen observation is created.
5. Sequence state may pause for bounces, failures, suppressions, complaints,
   or delays.

### Learn

1. Observations accumulate on batch items and contacts.
2. Operator requests a proposal for a batch.
3. Backend aggregates outcomes by persona, email quality, and top score
   component.
4. Proposal is stored for human review.
5. No production policy changes automatically.

## Configuration

Email sending:

- `ZOHO_MAIL_CLIENT_ID`
- `ZOHO_MAIL_CLIENT_SECRET`
- `ZOHO_MAIL_REFRESH_TOKEN`
- `ZOHO_MAIL_ACCOUNT_ID` optional, otherwise fetched from `GET /api/accounts`
- `ZOHO_MAIL_FROM_ADDRESS` optional, otherwise derived from configured sender
- `ZOHO_ACCOUNTS_BASE_URL`, defaults to `https://accounts.zoho.in`
- `ZOHO_MAIL_API_BASE_URL`, defaults to `https://mail.zoho.in`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `SMTP_FROM_NAME`
- `SMTP_REPLY_TO`
- `ALLOW_SEQUENCE_SEND`
- `EMAIL_TRANSPORT` optional override, `zoho_api`, `smtp`, or `resend`
- Resend-related configuration only if Resend is intentionally selected.

Lead-gen draft sends and notification draft sends force `zoho_api`. The shared
sender also prefers `zoho_api` when `ZOHO_MAIL_REFRESH_TOKEN` is configured.
SMTP remains as a fallback for hosts that allow outbound SMTP.

Zoho inbound:

- `ZOHO_IMAP_USER`
- `ZOHO_IMAP_PASSWORD`
- `ZOHO_IMAP_HOST`
- `ZOHO_IMAP_PORT`
- `ZOHO_IMAP_SENT_MAILBOX` optional, defaults to `Sent`

Resend webhook:

- `RESEND_WEBHOOK_SECRET`
- `RESEND_WEBHOOK_ALLOW_UNSIGNED`

Frontend:

- `NEXT_PUBLIC_API_URL`

Front read-only:

- Secret file currently referenced operationally:
  `/root/.openclaw/workspace/secrets/front_precise.env`
- Front must remain read-only for this lead-gen function.
- Default Front activity inboxes are Scheduling & Orders (`inb_qfq9`), Records
  & Images (`inb_rcld`), and AR Case Updates (`inb_37vb5`).

## Current Operational Notes

- Backend service: `autocaller-backend.service`.
- Frontend service: `autocaller-frontend.service`.
- Frontend dev server listens on port `3099`.
- Backend in this deployment listens on port `8099`.
- Backend health: `GET /health` returns `ok`.
- Use backend port `8099` for REST checks, not the Next.js frontend port.

Useful checks:

```bash
systemctl is-active autocaller-backend.service
systemctl is-active autocaller-frontend.service
curl -sS http://127.0.0.1:8099/health
curl -sS http://127.0.0.1:8099/api/lead-gen/policy/current
curl -sS -I http://127.0.0.1:3099/login
```

## Tests And Validation

Focused backend tests:

```bash
.venv/bin/pytest tests/test_outreach_phi_guard.py tests/test_front_sync.py tests/test_contact_selection.py tests/test_lead_gen_action_planner.py tests/test_sequence_templates.py
```

Frontend type check:

```bash
cd frontend
npx tsc --noEmit
```

Python compile check:

```bash
.venv/bin/python -m py_compile \
  app/services/contact_selection.py \
  app/services/front_sync.py \
  app/services/outreach_phi_guard.py \
  app/services/sequence_recommendations.py \
  app/services/lead_gen_action_planner.py \
  app/services/lead_gen_cybernetic.py
```

Whitespace check:

```bash
git diff --check
```

## Known Technical Boundaries

- Contact selection is deterministic code, not an LLM.
- Email composition uses the composer skill/LLM after contact selection.
- Every generated outbound email currently requires human approval.
- Policy proposals do not apply themselves.
- There is no first-class suppression table yet.
- Front warmth is ingested behind inactive `lead-gen-v2`; orchestrator/operator
  review is required before activation.
- Resend webhook code exists, but production must be configured with a deployed
  webhook URL and `RESEND_WEBHOOK_SECRET`.
- The file name `OperatorNotificationPopup.tsx` is legacy; the component is now
  a non-blocking action center.
