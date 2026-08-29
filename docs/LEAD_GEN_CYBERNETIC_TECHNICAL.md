# Lead Gen Cybernetic Technical Implementation

This is the engineering map for the Possible Minds lead-generation cybernetic
function. Keep this file focused on what exists, where it lives, how data
moves, and how to operate or test it.

Use the other lead-gen docs for different purposes:

- Conceptual design: `docs/CYBERNETIC_LEAD_GEN_CONCEPT.md`.
- Active backlog: DB-backed `todos` table, exposed through `/todos` and
  `bin/possibleos todos ...`.
- Historical session handoff: `docs/CYBERNETIC_LEAD_GEN_SESSION.md`.

## Runtime Surfaces

### Backend

FastAPI serves the lead-gen APIs through `app/api/lead_gen.py` and related
sensor routes.

Important routes:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/lead-gen/policy/current` | active policy, weights, suppressions, daily send budget |
| `PUT` | `/api/lead-gen/settings/daily-send-budget` | persist daily send budget on active policy (preserves an operator-set transport strategy / Zoho cap) |
| `GET` | `/api/lead-gen/settings/transport` | read the transport send-order strategy + resolved per-provider daily caps |
| `PUT` | `/api/lead-gen/settings/transport` | set `lead_gen_transport_strategy` (`zoho_first_then_resend` \| `resend_first_then_zoho`) and/or `provider_daily_caps` (`zoho_api`, `resend`) on the active policy; CLI: `lead-gen transport` |
| `POST` | `/api/lead-gen/batches` | create a daily action plan batch; with `curated: true`, create an empty operator-curated batch with initialized counts metadata |
| `POST` | `/api/lead-gen/email-agent/slice` | create a bounded email-agent slice with research evidence, composer drafts, and durable `send_email mode=lead_gen` actions |
| `POST` | `/api/lead-gen/daily-run` | run or dry-run the checkpointed daily lead-selection and drafting pipeline |
| `POST` | `/api/lead-gen/daily-run/top-up` | add fresh first-touch sends to today's run-date via a sidecar daily batch, excluding contacts already batched that run date |
| `GET` | `/api/lead-gen/daily-runs` | list recent daily-run checkpoints |
| `GET` | `/api/lead-gen/daily-run/throughput` | read the daily send-throughput funnel, target verdict, auto-send state, history counts, and held firms needing review evidence |
| `GET` | `/api/lead-gen/daily-run/enabled` | read the persisted daemon-loop flag, default false |
| `PUT` | `/api/lead-gen/daily-run/enabled` | enable or disable the default-off daily-run daemon loop |
| `GET` | `/api/lead-gen/batches` | list batches |
| `GET` | `/api/lead-gen/batches/{batch_id}` | get batch, items, optional observations, and each item's `predicted_transport` display hint |
| `POST` | `/api/lead-gen/batches/{batch_id}/add-contacts` | add explicit `firm_contacts` ids/emails to a curated batch idempotently and repair `counts_json` from the live item count |
| `POST` | `/api/lead-gen/batches/{batch_id}/resolve-linkedin` | resolve missing direct personal LinkedIn `/in/` URLs for batch contacts, defaulting to decision-makers only and capped at 25 live web_search calls |
| `POST` | `/api/lead-gen/batches/{batch_id}/recount` | repair `counts_json.returned`/`requested` from live `lead_gen_batch_items` |
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
| `GET` | `/aiaudit/go?t=<signed-token>` | public AI Audit redirect; verifies token, writes `audit_link_clicks`, records `link_clicked`, redirects to `AIAUDIT_PUBLIC_URL` with non-PHI prefill |
| `GET` | `/v/<code>` | public AI Visibility report redirect; resolves `visibility_links`, writes `audit_link_clicks` with `source=visibility_report_email`, records `link_clicked`, redirects to `AIVIS_REPORT_BASE_URL/r/<scan_id>?c=<click_id>&src=visibility_report_email` |
| `POST` | `/api/engagement-campaigns` | create one dated, channel-neutral campaign |
| `GET` | `/api/engagement-campaigns?search=...` | list or look up campaigns by name/workflow |
| `GET` | `/api/engagement-campaigns/activity/latest?since_days=1&quality=human` | newest-first activity across campaigns, classified with the same human/scanner session rules used by campaign detail |
| `GET` | `/api/engagement-campaigns/<id>` | campaign summary, channel rollups, links, and classified activity |
| `POST` | `/api/engagement-campaigns/<id>/links` | create a unique email, LinkedIn, or public `/t/<code>` URL for an allowlisted Possible Minds page |
| `POST` | `/api/engagement-campaigns/links/<code>/mark-sent` | mark an operator-sent touch without claiming delivery/read status |
| `GET` | `/t/<code>` | public campaign redirect; writes `engagement_campaign_clicks`, records `link_clicked`, and redirects with opaque `lc`/`c` plus campaign UTM fields |
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
| `POST` | `/api/research/warm` | trigger budgeted PIF Stats research over the Front warm list |
| `GET` | `/api/research/status` | research coverage counts and open PIF Stats task rows |

### CLI

Lead-gen CLI commands live in `app/cli.py` under the `lead-gen` group.

Primary commands:

```bash
bin/possibleos lead-gen policy
bin/possibleos lead-gen recommend --template possible_minds_dynamic --limit 50
bin/possibleos lead-gen create-batch --name "Curated owner outreach"
bin/possibleos lead-gen add-contacts <batch_id> --contact <firm_contacts.id-or-email>
bin/possibleos lead-gen add-contacts <batch_id> --from /tmp/contacts.json
bin/possibleos contacts resolve-linkedin-batch <batch_id> --limit 25
bin/possibleos lead-gen recount <batch_id>
bin/possibleos lead-gen email-agent-slice --limit 3 --approval-ready
bin/possibleos lead-gen email-agent-slice --limit 3 --approve-actions --policy-check-first-action --json
bin/possibleos lead-gen daily-run --dry-run
bin/possibleos lead-gen daily-run
bin/possibleos lead-gen top-up --count 20 --variant ai-audit
bin/possibleos lead-gen daily-status
bin/possibleos lead-gen throughput
bin/possibleos lead-gen daily-enable
bin/possibleos lead-gen daily-disable
bin/possibleos lead-gen batches
bin/possibleos lead-gen show <batch_id> --observations
bin/possibleos lead-gen edit-draft <batch_item_id> --at "10:30 PT"
bin/possibleos lead-gen approve <batch_id>
bin/possibleos lead-gen approve <batch_id> --start-sequences
bin/possibleos lead-gen observe --event-type email_reply --item <batch_item_id> --text "..."
bin/possibleos lead-gen observations --since 7d
bin/possibleos lead-gen observations --since 7d --type email_sent --contact <contact_id>
bin/possibleos lead-gen observations summary --since 7d
bin/possibleos aiaudit link --contact <contact_id>
bin/possibleos aiaudit clicks --since 7d
bin/possibleos visibility-clicks --days 7
bin/possibleos lead-gen propose <batch_id>
bin/possibleos front sync --max-calls 300
bin/possibleos front status
bin/possibleos front contacts --domain examplelaw.com
bin/possibleos front warm-batch --domains examplelaw.com,anotherfirm.com
bin/possibleos research status --tasks
bin/possibleos research firm examplelaw.com --staff --behavior
bin/possibleos research warm --top 50 --kinds research,staff
bin/possibleos research sync
bin/possibleos personas map
bin/possibleos personas show examplelaw.com
bin/possibleos leads warm-list --limit 20
bin/possibleos actions list --type send_approved_lead_gen_draft
bin/possibleos actions list --scheduled
bin/possibleos actions scheduler-status
bin/possibleos actions show <action_id>
bin/possibleos actions policy-check <action_id>
bin/possibleos actions execute <action_id>
bin/possibleos actions cancel <action_id> --reason "operator changed plan"
bin/possibleos actions reschedule <action_id> --at "11:00 PT"
bin/possibleos actions execute-approved-lead-gen --limit 1 --actor master-agent
bin/possibleos actions send-approved-lead-gen-draft --item <batch_item_id> --subject "..." --body "..." --at "09:30 PT"
bin/possibleos actions send-email --mode lead_gen --to <email> --subject "..." --body "..." --contact <contact_id> --item <batch_item_id> --at "2026-06-11T09:30:00-07:00"
bin/possibleos listening brief
bin/possibleos listening search "medical records follow up" --limit 8
bin/possibleos listening prep "<firm-or-name>"
bin/possibleos inbound poll --limit 50 --classify
bin/possibleos todos list --area lead-gen
bin/possibleos todos add "Review new workflow idea" --area lead-gen --source-url https://...
bin/possibleos todos update <id> --status done
bin/possibleos todos delete <id>
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
  signals, matched `pif_id`, `warm_score`, and nullable `behavioral_json`
  copied from completed PIF Stats behavior analysis.
- `front_sync_state`: per-stage cursor and watermark.
- `firm_contacts` now has nullable `front_contact_id`, `front_last_seen`, and
  `tech_signals` columns. Firm research also adds nullable `persona`,
  `persona_source`, `persona_confidence`, and `research_title` columns.

Operational constraints implemented:

- Front credentials load from
  `/root/.openclaw/workspace/secrets/front_precise.env` via dotenv.
- API stages are read-only GETs.
- `FrontRateBudget` hard-caps calls per run and enforces at least 1.5 seconds
  between calls.
- HTTP 429 responses are handled in `FrontClient.get`: the client honors
  `Retry-After` (clamped 1–60s), doubles the run's pacing interval (capped at
  15s), retries up to twice, and counts events in `rate_limited` (surfaced in
  stage stats, the persisted last-run payload, and `GET /api/front/status` /
  `front status`). Persistent 429s raise and abort the run with the cursor
  already persisted, so the next run resumes where it stopped.
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
  score breakdown and source features. When a contact has a mapped persona, the
  batch item uses that persona key instead of the generic `front_warm_contact`.

### PIF Stats Firm Research Orchestrator and Personas

Files:

- Schema: Alembic revision
  `p8q9r0s1t2u3_add_firm_research_orchestrator.py`; ORM rows
  `ResearchTaskRow`, the new contact persona columns, and
  `FrontFirmActivityRow.behavioral_json`.
- Service: `app/services/firm_research.py`.
- Persona mapper: `app/services/persona_mapper.py`.
- API: `app/api/research.py` exposes `/api/research/warm` and
  `/api/research/status`.
- CLI: `research firm`, `research warm`, `research status`, `research sync`,
  `personas map`, and `personas show`.

Operational constraints implemented:

- No daemon loop exists for research. Operators or agents must trigger research
  explicitly.
- `PifStatsClient` uses `PIF_BASE` or `PIFSTATS_BASE_URL`, defaults to the
  existing Precise PIF Stats base, and only calls:
  `POST /pif-info/{pif_id}/research`,
  `POST /pif-info/{pif_id}/research-staff`,
  `POST /pif-info/{pif_id}/analyze-behavior`,
  `GET /pif-info/research-status/{task_id}`, and
  `GET /pif-info/{pif_id}`.
- Task-creating POSTs have a hard default budget of 30/run, >=2s spacing, and
  429 retry handling that honors `Retry-After`, widens pacing, and burns budget
  on retries. GETs are paced at >=0.5s.
- If PIF Stats starts requiring auth, credentials are read from env
  (`PIFSTATS_AUTH_TOKEN`, `PIF_AUTH_TOKEN`, `PIFSTATS_API_KEY`, or
  `PIFSTATS_AUTH_HEADER`), never hardcoded.
- Completed leadership/staff payloads upsert into `firm_contacts`, matching by
  `(pif_id, email)` when email exists and `(pif_id, name)` otherwise. Research
  titles are stored separately in `research_title`.
- Completed behavior analysis copies `behavioral_data` into
  `front_firm_activity.behavioral_json` for all rows with the same `pif_id`.
- `compose_lead_email` includes mapped `contact.persona` fields and
  `front_signals.behavior` so the composer skill can use after-hours ratios,
  primary pain points, and topic distributions as evidence.
- `persona_mapper` maps title keywords and functional email prefixes to the
  composer persona keys: `founder_owner`, `managing_partner`, `coo_ops`,
  `intake`, `records`, `case_manager`, `lien_settlement`, `marketing`,
  `attorney`, and `paralegal`. It is idempotent and never replaces an existing
  higher-confidence persona with a lower-confidence source.

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
| `link_clicked` | tracked `link_events` click attributed to an outreach send, `audit_link_clicks` from `/aiaudit/go` or `/a/<code>` (`raw_event_json.channel = "ai_audit"`), consult-link clicks from `/c/<code>` (`channel = "consult"`, `source = consult_email`; reuses `audit_links` with `kind=consult`, 302s to `getpossibleminds.com/consult`), solution/product-link clicks from `/s/<code>` (`channel = "solution"`, `source = solution_email`, `kind=solution`, 302s to the outbound voice-AI solution page with `?lc=<code>`), AI Visibility report clicks from `/v/<code>` (`channel = "ai_visibility"`), or workshop-link clicks from `/w/<code>` (`channel = "workshop"`, `kind=workshop`). Email workshop links (`source = workshop_email`) retain one-click contact prefill; LinkedIn workshop links (`source = workshop_linkedin`) redirect with opaque `lc`/`c` values only so contact PII does not enter the visible URL. | deterministic opened-or-clicked |
| `product_interest` | early-access / design-partner signup from a product solution page via `POST /api/lead-gen/product-interest` (public). `raw_event_json` carries `email`, `firm`, `product`, `channel = "solution"`; attributed to a contact/batch_item when the `/s/` link code (`lc`) is supplied. Workshop registration pages (`product = "workshop-*"`, `source = "workshop_page_register"`) additionally send optional ICP-qualification fields `role`, `case_management_system`, `firm_size`. Every signup fires a best-effort operator alert (WhatsApp via openclaw CLI to `OPERATOR_WHATSAPP`, Telnyx SMS fallback — SMS to the +91 operator number fails DLT rules, hence WhatsApp-first; `app/services/operator_sms.py`); `workshop-*` products additionally send the registrant a plaintext confirmation email via Resend (`send_workshop_registration_confirmation`, `message_type=workshop_registration_confirmation` in `email_logs`). Notification failures never fail the signup | deterministic high-intent product signal |
| `page_session` | JS beacon from a tracked landing page via `POST /api/lead-gen/page-event` (public). `raw_event_json.event` is a progressive-funnel step: `session_ready`, `first_pointer`, `scroll_25`/`scroll_50`/`scroll_75`/`scroll_90`, `content_revealed`, `click`, or `page_leave`. Trusted browser interaction is recorded separately from a bare JS load. Events share a client-generated `session_id`; attribution comes from `/s/`, `/c/`, `/w/`, or campaign `/t/` link code (`lc`). The emitter is the global `ClickBeacon` in the getpossibleminds root layout, so every non-admin website page can participate. | deterministic; session-level quality classified at rollup time (see below) |

### Cross-channel daily campaigns

`engagement_campaigns` is the dated reporting cohort. Each
`engagement_campaign_links` row is one channel/contact/public touch and carries
its own destination; `engagement_campaign_clicks` is the raw redirect log. The
destination allowlist accepts HTTPS URLs on `getpossibleminds.com` and its
subdomains only, preventing the public resolver from becoming an open redirect.
The marketing site rewrites `/t/<code>` to Possible OS and runs `ClickBeacon`
globally. The beacon's `lc` is resolved server-side to campaign, channel, and
optional contact; recipient PII is never required in the destination URL.

Campaign analytics count raw redirect fetches separately from classified page
sessions. Known scanner user agents are scanner; a page load or quick bounce
without meaningful interaction is unconfirmed; clicks, scroll milestones, and
reveal actions establish a human session unless a scanner signature overrides
them. Campaign totals deduplicate engaged people while channel rollups preserve
the direct touch that produced the visit.
| `consult_booked` | website consult booking or Cal.com booking made during a call | deterministic booked qualified conversation |
| `call_disposition` | judge persistence after outbound call review finalizes GTM disposition | deterministic mapping from GTM disposition |
| `email_action_cancelled` | approved/waiting lead-gen email action cancellation | deterministic audit trail |
| `email_rescheduled` | scheduled lead-gen email action moved to a new time | deterministic audit trail |

#### Wave-rollup session quality (`classify_page_sessions`)

`GET /api/lead-gen/batches/{batch_id}/experiment-rollup` (CLI:
`bin/possibleos lead-gen wave-rollup <batch_id>`) classifies page sessions at
the **session** level, not per observation. `page_session` observations are
grouped by `raw_event_json.session_id` (falling back to the observation id)
in `app/services/lead_gen_experiments.py::classify_page_sessions`. A
`session_ready` beacon alone is **not** human evidence — email-security
scanners execute JS too (observed on the 2026-07-13 workshop wave:
session_ready + ~4s `page_leave` dwell, zero click events, arrival within
~2 minutes of the send). A session is `human` only with interaction evidence:

- `page_leave` dwell above `HUMAN_SESSION_MIN_TIME_ON_PAGE_MS` (10s), or
- at least one on-page `click` event in the same session, or
- first activity later than `HUMAN_SESSION_MIN_DELAY_AFTER_SEND` (15 min)
  after the item's `email_sent` observation.

Sessions matching `SCANNER_UA_PATTERNS` are `scanner`; everything else without
evidence is `suspect`. The rollup's `measurement` block reports
`raw_page_sessions` (every distinct session, unfiltered) alongside
`human_page_sessions` / `suspect_page_sessions` / `scanner_page_sessions`, and
`signal_quality.page_sessions` carries the same session-level breakdown. The
per-observation labels in `signal_quality.observations` use the same 10s dwell
threshold (`signal_quality()`), mirroring the click classifier's stance that a
browser user agent alone is never proof of a human.

**Progressive-funnel gestures are the high-confidence human signal.** Modern
email-security scanners execute page JS *and* can emulate dwell, so dwell alone
(and, to a lesser extent, delayed arrival) is no longer reliable — the
2026-07-13 workshop wave showed scanners holding pages open ~15–25s and rotating
spoofed UAs. The trustworthy evidence is a *gesture* a scanner does not perform:
`first_pointer`, `scroll_50`, `content_revealed`, or an on-page `click`.
`classify_page_sessions` returns per session `{quality, reached_reveal,
has_gesture}`, and the rollup adds two gesture metrics:

- `gesture_page_sessions` — sessions with any funnel gesture (the number to
  trust over `human_page_sessions`, which still includes the weaker dwell/late
  fallbacks).
- `revealed_page_sessions` — sessions that tapped `content_revealed`, the
  strongest pre-conversion signal (a human chose to unlock the gifted content).

The landing page is designed to *manufacture* these gestures: the gifted payload
(e.g. workshop "instruction one") sits behind a `RevealPanel` tap-to-reveal, so a
genuine reader produces a `content_revealed` event a scanner never will. The
north-star remains the conversion itself (`product_interest` registration /
`consult_booked`), which no scanner performs.

`GET /api/aiaudit/workshop-click-analytics` and `lead-gen workshop-analytics`
power the workshop-only `/click-analytics` operator view. They join `/w/`
redirects to attributed `page_session` observations, collapse duplicate global
and page-specific beacons, and expose the exact `content_revealed`, `click`, and
`scroll_50` actions per contact. This view deliberately does not accept
`first_pointer` by itself as human proof: observed preview automation can emit a
synthetic pointer before leaving after roughly four seconds. Known scanner UAs
and short load/pointer/leave-only sessions remain scanner or suspect signals.

The weekly learning KPI is:

```bash
bin/possibleos lead-gen observations summary --since 7d
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

The edit path also accepts `lead_gen_action_type` (`first_touch`, `follow_up`,
`reply_to_inbound`, or `approve_existing_draft`). It stores the classification
as `input_json.lead_gen_action_type` on the durable action and
`reason_json.action_type` on the batch item. Send Queue reads those fields and
only falls back to `first_touch` when both are absent.

If a batch item has `last_sent_at` or `last_sent_message_id` and no live
editable action, `edit-draft` now refuses to create a second action on that
item. Operators must create a fresh batch item for a subsequent follow-up,
preventing the preview from presenting historical sends as the new draft.

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
- at least one lead-gen transport has remaining provider capacity today
  (`zoho_api` first, capped by policy, then `resend`);
- active daily budget is readable and greater than zero;
- no prior successful `lead_gen` action exists for the same batch item;
- no prior successful `lead_gen` action exists for the same recipient.

Execution chooses the lead-gen transport from policy/provider caps, sends
through `_send_email(..., transport=...)`, then writes send metadata back onto
both the durable action result and `lead_gen_batch_items.reason_json`.

The send order and caps are operator-configurable on the active policy via
`set_lead_gen_transport(strategy, zoho_cap, resend_cap)` (REST
`PUT /api/lead-gen/settings/transport`, CLI `lead-gen transport`). Strategy
`zoho_first_then_resend` (default) fills Zoho up to its cap before spilling to
Resend; `resend_first_then_zoho` reverses that. Setting `zoho_cap = 0` forces
the Resend-only path.

**Per-send transport override.** A `transport` value on the send action payload
(`resend` | `zoho_api` | `smtp`) is *authoritative* — `_execute_send_email` and
`send_batch_item_draft` use it directly and skip the policy strategy/cap
selection entirely. The automatic strategy only applies when no explicit
transport is set (e.g. the daily-run and agent-slice paths). All CLI email-send
commands (`actions send-email`, `actions send-test-email`,
`actions send-approved-lead-gen-draft`) **require** `--transport` so an
operator send is never routed to an opaque, auto-selected provider; the request
models (`EmailActionRequest`, `TestEmailActionRequest`, `LeadGenDraftActionRequest`)
carry it and `create_send_email_action` /
`create_send_approved_lead_gen_draft_action` persist it in the action
`input_json`. This is a deliverability control: Resend sends from
`getpossibleminds.com` (aligned with the report link domain) and lands in the
inbox, whereas the Zoho path sends from `possiblemindshq.com` over a shared
Zoho India IP and is prone to junk-foldering. The strategy and an explicit
`zoho_api` cap are preserved across UI daily-budget saves.

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
- Both action types store optional `in_reply_to` and `references` RFC
  Message-ID ancestry. The executor maps these to standard SMTP/Resend headers
  and Zoho Mail API `inReplyTo` / `refHeader` fields. Approval metadata binds
  the ancestry values, and policy re-checks them before execution.
- `lead-gen edit-draft --transport ... --in-reply-to ... [--references ...]`
  updates an existing scheduled action in place and clears its prior policy
  result. Provider UUIDs are not accepted as RFC Message-IDs.
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
bin/possibleos agents config \
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
   insights. All gateway calls target the `openclaw/proxy` agent, never the
   main `openclaw` agent — see the CLAUDE.md standing rule "OpenClaw gateway:
   always use the `openclaw/proxy` agent". The main agent carries the
   `active-memory` extension (daily memory-file dependency) that is overhead
   and a failure surface for stateless completions.
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
- seed a sequence after a successful first-touch daily lead-gen send when
  `SEQUENCES_ENABLED` is true;
- render or compose due steps;
- create operator approval notifications for dynamic generated outbound emails;
- send only when allowed by execution gates;
- advance sequence state and cadence.

Execution gate:

- Daily first-touch sends only create sequence rows when `SEQUENCES_ENABLED` is
  truthy (`1`, `true`, `yes`, or `on`). The default is off, so the daily
  pipeline does not create sequence rows unless explicitly enabled.
- The dynamic Possible Minds template defaults to three steps at absolute day
  offsets `0,3,7`. `SEQUENCE_STEPS` and `SEQUENCE_CADENCE_DAYS` can override
  those values when needed.
- Actual scheduled sequence sending still requires `ALLOW_SEQUENCE_SEND=true`.
- Successful follow-up `send_email mode=lead_gen` actions advance the existing
  sequence row to the sent step, set `last_sent_at`, reactivate it with the
  next cadence gap, or mark it completed after the final step.

TODO:

- Add an optional fresh-lead floor mode if strict follow-ups-first starves
  first touches.
- Add stop-on-bounce and unsubscribe handling beyond the existing reply pause
  and delivery-risk pauses.

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
- `lead_gen_daily_runs`
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
- `lead_gen_daily_runs.stages_json`
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

### Daily Run Pipeline

`app/services/lead_gen_daily.py` owns the deterministic daily run. A real run
creates or resumes one `lead_gen_daily_runs` row per Pacific run date and
checkpoints these stages in `stages_json`: `gates`, `signals`, `research`,
`personas`, `select`, `batch`, `compose`, `schedule`, and `notify`.

Important behavior:

- Gates require `system_enabled=true`, active policy `daily_send_budget > 0`,
  an allowed weekday, and no recent deliverability circuit breaker. The breaker
  trips when the last 48h has at least four sends and
  `email_send_failed`/bounce observations exceed the policy threshold
  (`deliverability_circuit_breaker_threshold`, default `0.25`).
- If Front sync is stale by more than 30 hours, the run calls local
  `resolve_firms()` and `refresh_warm_scores()` only; it does not call Front.
- Research queues bounded PIF Stats warm-firm research and behavior tasks using
  `daily_research_budget` (default `10`) and proceeds on timeout. Research
  errors are non-fatal.
- Persona mapping runs before selection.
- With `SEQUENCES_ENABLED=false` (default), selection uses
  `recommend_sequence_contacts`, excludes `precisemri.com` and Front
  suppress-flagged firms, applies `daily_persona_quota`, keeps one contact per
  firm, then fills any shortfall by score order up to `daily_batch_size`
  (default `20`).
- With `SEQUENCES_ENABLED=true`, the daily run is the sole owner of the daily
  lead-gen email quota. It selects due active sequence follow-ups first
  (`next_step_due_at <= now`, oldest due first), then fills only the remaining
  capacity with fresh first-touch contacts. If due follow-ups meet or exceed
  `daily_batch_size`, fresh selection is zero for that run.
- The batch is named `Daily run YYYY-MM-DD`. Item `reason_json` includes
  `basis=daily-run`, quota, selection features/suppressions, and behavior facts
  from `front_firm_activity.behavioral_json`. Follow-up items also include
  `action_type=follow_up`, `sequence_id`, and `step_num`.
- `top_up_daily_run(n, composer_variant_key=...)` resolves the same run date
  (`DAILY_RUN_TZ`, default Asia/Kolkata), builds an exclusion set from every
  contact already in a daily-run or daily-run top-up batch for that date, selects
  only fresh first-touch contacts through `_select_contacts`, creates a sidecar
  batch named `Daily run YYYY-MM-DD top-up`, composes via `_compose_batch`, and
  schedules/auto-approves via `_schedule_drafted_items`. The REST endpoint is
  `POST /api/lead-gen/daily-run/top-up` with `{ "n": 1..40,
  "composer_variant_key": "..." }`; the CLI wrapper is
  `lead-gen top-up --count N [--variant <key>]`.
- Compose reuses the existing batch-compose path in chunks of five, leaving
  transient failures as `partial` so the next run resumes undrafted items.
  Follow-up items compose with the claimed sequence row and next step number,
  so the composer uses follow-up framing rather than the first-touch opener.
- Due follow-up rows selected by the daily run are paused as
  `awaiting_operator_send_approval:daily_run:<run_id>` when the batch is
  created. The autonomous sequence loop selects only `active` rows with a due
  timestamp, so it skips daily-run-claimed follow-ups and cannot double-draft
  the same step.
- Schedule spreads drafted items across `daily_send_window` (default
  `09:00-11:30 America/Los_Angeles`) and leaves every action in
  `waiting_for_approval`. The scheduled-action daemon only drains `approved`
  actions, so these cannot send without operator approval.
- Notify shells out to `openclaw message send --channel whatsapp ...` with a
  45-second timeout. Delivery verification is intentionally outside this
  service.

`daily-run --dry-run` is no-write and no-side-effect: it evaluates gates,
Front staleness, and selection, but it does not create batches, actions, PIF
Stats tasks, or WhatsApp messages.

The daemon loop is wired in `app/main.py` but reads persisted
`system_settings.agent_config.daily_run_enabled`. The default is false, so a
daemon restart never starts the pipeline unless an operator explicitly enables
it with CLI/API/UI.

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
8. When `SEQUENCES_ENABLED=true`, a successful daily first-touch
   `send_email mode=lead_gen` action seeds a dynamic sequence at
   `current_step=1` so the scheduler resumes at step 2 and never re-sends the
   opener.

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

LLM model routing (lead-gen + adjacent text tasks):

- The lead-gen **composer**, **lead-extractor**, and **name classifier** call the
  OpenClaw **proxy gateway** (`call_skill_json`), which authenticates to OpenAI
  via **ChatGPT OAuth** ("Sign in with ChatGPT"), not a platform `sk-` API key.
  Each is driven by a `SKILL.md` under `app/skills/` and parses tolerant JSON.
- `LEAD_EMAIL_COMPOSER_MODEL` (default `openclaw/proxy`) — composer agent/model.
- `LEAD_EXTRACTOR_MODEL` (default `openclaw/proxy`) — `app/services/lead_extractor.py`
  via `app/skills/lead-extractor/SKILL.md`. (Was direct `gpt-4o-mini`; migrated
  to OAuth/gateway, D-2026-06-22-02.)
- `LEAD_NAME_CLASSIFIER_MODEL` (default `openclaw/proxy`) — the
  `leads backfill-names` person-vs-firm classifier, via
  `app/skills/lead-name-classifier/SKILL.md`.
- `PHONE_SIM_REPLY_MODEL` (default `openclaw/proxy`) — the local voice-call
  simulator reply (`app/llm.py`), via `app/skills/phone-sim-reply/SKILL.md`.
- **Still on the platform `OPENAI_API_KEY` (cannot use OAuth):** STT (Whisper),
  TTS, the Realtime calling engine — all audio, which the OAuth/gateway path
  can't serve — and the **live IVR navigator** (`IVR_NAV_MODEL`, default
  `gpt-4o-mini`), kept on the fast direct API for latency. The judge
  (`app/services/judge.py`) also remains on direct `gpt-4o-mini`.

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
- `SEQUENCES_ENABLED`
- `SEQUENCE_STEPS`
- `SEQUENCE_CADENCE_DAYS`
- `ALLOW_SEQUENCE_SEND`
- `LEAD_GEN_FIRST_TOUCH_VARIANT` — composer variant key forced on first-touch
  (non-follow_up) items in `_compose_batch_items`. Defaults to `review-evidence`
  (Phase 3); set empty to disable forcing (first-touch then uses the random A/B
  rendezvous pool). An explicit `composer_variant_key` (preview "compare
  variants") always overrides. Follow-up steps are never forced. The
  `review-evidence` variant frames the first-touch hook by
  `review_evidence.primary.kind` — **complaint** ("we fix this"), **praise**
  ("scale what you're known for"), **outcome** (credibility), **fact**
  (research-proof personalization) — citing the item verbatim + attributed
  (facts use `paraphrase`, never a fabricated quote), and falls back to a clean
  baseline email when no usable evidence exists. `allocation_weight=0` (forced
  only, never random A/B). The legacy `yelp-pain-quote` variant is RETIRED
  (`active=false`), superseded by `review-evidence`.
- `LEAD_GEN_FOLLOW_UP_VARIANT` — composer variant key forced on follow-up
  (`action_type=follow_up`) items in `_compose_batch_items`, symmetric to the
  first-touch knob. Default `""` = unchanged behavior (follow-ups use the random
  A/B rendezvous pool over weight>0 variants). Set e.g. `ai-audit` to drive the
  audit CTA on follow-ups. A per-run/explicit `composer_variant_key` still wins.
- **Per-run/top-up composer override** — `composer_variant_key` on
  `POST /api/lead-gen/daily-run` or `/api/lead-gen/daily-run/top-up` (and
  `--variant` on `lead-gen daily-run` / `lead-gen top-up`, plus the "Composer
  variant (this run)" picker in the Daily run panel) pins one active variant on
  every composed email in that run, taking precedence over both env knobs and
  the A/B. It is plumbed through `_compose_batch →
  _compose_batch_items(composer_variant_key=...)` and validated against active
  variants (400 on unknown). Daily runs record
  `compose.counts.composer_variant_override`; top-ups return
  `composer_variant_override` in the endpoint payload. Precedence:
  per-run/top-up/explicit key > `LEAD_GEN_*_VARIANT` env > auto A/B.
- `REVIEW_EVIDENCE_GATE_KINDS` (default `complaint,praise,fact`) — which evidence
  kinds count as "enough to personalize a first-touch email." Used by both the
  compose gate and the composer's primary-hook pick (via
  `evidence_gate_kinds()`), so they agree. Set `=complaint` for the strict
  old behavior (only firms with a real grievance compose).
- `LEAD_GEN_EVIDENCE_AWARE_SELECTION` (default `true`) — daily fresh first-touch
  selection prefers firms that already have usable review evidence (so slots
  fill with composable, not gate-held, firms), reserving
  `LEAD_GEN_NO_EVIDENCE_RESERVE` (default `3`) slots for top no-evidence firms to
  keep the paste-reviews discovery loop fed. Candidate pool widened to
  `batch_size*10`. The binding constraint becomes evidence coverage among
  *eligible* (not-recently-contacted) firms.
- `LEAD_GEN_AUTO_APPROVE_SEND` (code default `false`; **enabled in this deploy's
  `.env`**) — autonomous send: `_schedule_drafted_items` creates/flips scheduled
  send actions to `approved` so the action scheduler sends them at their window
  slot without a manual approval click. **This removes only the human approval
  step.** Every send still passes `check_action_policy` (the PHI egress guard)
  at execution, spreads across the 9–11:30 PT window, and respects the
  deliverability breaker + suppression. Code default stays OFF so a fresh deploy
  never auto-sends. (Operator-authorized 2026-06-17, D-2026-06-17-26.)
- `OUTREACH_PHI_GUARD_LLM_ENABLED` (default `true`; **set `false` in this deploy**)
  — when false, the PHI egress guard skips its LLM classifier and passes any body
  that clears the **deterministic** PHI regex (DOB / MRN / case# / patient-context,
  which always run and always block). Disabled because outreach legitimately cites
  public Yelp review quotes that the strict classifier over-flags as "identifiable
  individuals." Re-enable (or switch the review-evidence variant to anonymized
  attribution) for the durable fix. (Operator-authorized 2026-06-17.)
- `REQUIRE_REVIEW_EVIDENCE_FIRST_TOUCH` — when truthy (default `true`),
  first-touch items whose firm has **no usable review evidence of the allowed
  kinds** are **blocked**: `_compose_batch_items` skips composition, queues no
  send, marks the batch item `reason_json.held_reason="awaiting_review_evidence"`
  (clearing any prior `agent_draft`), and leaves it undrafted so a re-run
  composes once evidence exists. The firm is still selected, so the
  `yelp_review_needed` action-center prompt still fires. Follow-ups are never
  gated. Resolved evidence-exempt first-touch variants (`ai-audit`) bypass this
  hold because they use a generic AI-readiness pitch rather than review evidence.
  Legacy alias `REQUIRE_YELP_QUOTE_FIRST_TOUCH` is still honored. Set `0`/`false`
  to disable the gate.
- `REVIEW_AUTO_EXTRACT` (default `true`) — when on, pasting raw Yelp reviews via
  `PUT /api/firms/{pif_id}/reviews` fires a background extraction
  (`app/services/review_extraction.py`) that writes the `<!-- EXTRACTED v1 ... -->`
  block read by the gate + composer. The lead-gen compose gate also calls
  `ensure_review_extracted` as a pre-gate safety net (self-heals firms whose raw
  reviews slipped through). Extraction is idempotent — it re-runs only when the
  raw text changes (tracked by `content_hash`). `REVIEW_EXTRACTOR_MODEL` (default
  `openclaw/proxy`) selects the gateway agent. Manual control:
  `bin/possibleos reviews extract <pif_id> [--force]` and
  `bin/possibleos reviews extract-all-pending [--limit N] [--force]`; REST:
  `POST /api/firms/{pif_id}/extract`. The extraction system prompt is
  `app/skills/review-quote-extractor/SKILL.md` (single-shot, strict v1 JSON);
  the `yelp-review-quotes` skill remains the human/agent runbook.

  **v2 review-intelligence schema (Phase 1).** Extraction now emits an
  `<!-- EXTRACTED v2 ... -->` block with a flat list of typed **evidence
  items** — `kind` ∈ {complaint, praise, fact, request, outcome}, an open
  snake_case `theme`, verbatim `quote` (or `paraphrase` for facts), `sentiment`,
  `confidence`, and an `outreach_usable` safety flag — plus `themes_present`,
  `themes_absent`, and a `firm_summary`. The generalized reader
  `fetch_review_evidence(pif_id, kinds=, themes=, min_confidence=,
  outreach_usable_only=, limit=)` returns a ranked slice for any purpose and
  understands **both** v1 (`pain_points`, mapped to kind=complaint) and v2
  blocks, so old extractions keep working. `fetch_pain_quote_for_firm` is now a
  thin back-compat wrapper (`kinds={complaint}, themes={client_communication},
  outreach_usable_only=True`) — the gate and yelp-pain-quote composer variant
  are UNCHANGED and stay complaint-only. Broadening the gate/composer to praise
  and facts (using `kind`) is Phase 3; this phase only ships the capability.
- `EMAIL_TRANSPORT` optional override, `zoho_api`, `smtp`, or `resend`
- Resend-related configuration only if Resend is intentionally selected.

Lead-gen draft sends route through the provider-aware lead-gen transport policy:
Zoho API first, capped at 20/day by default, then Resend for the remaining daily
budget. Notification draft replies still force `zoho_api` so replies stay tied to
the mailbox thread. The shared sender also prefers `zoho_api` when
`ZOHO_MAIL_REFRESH_TOKEN` is configured. SMTP remains as a fallback for hosts
that allow outbound SMTP outside the lead-gen path.

The `/lead-gen` draft review UI reads `predicted_transport` from each item in
`GET /api/lead-gen/batches/{batch_id}`. Shape:
`{"channel":"zoho_api"|"resend"|"over_budget"|"sent:<transport>",
"scheduled_for":<iso|null>,"sent_at"?:<iso|null>,"action_id"?:<id|null>,
"status"?:<status|null>}`. The backend computes this globally per PT send day:
already-sent lead-gen actions keep their recorded email-log transport, and
approved not-yet-started `send_email mode=lead_gen` actions scheduled for that
day consume the configured provider caps in `scheduled_for, id` order using the
active `lead_gen_transport_strategy` (`zoho_first_then_resend` or
`resend_first_then_zoho`).

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

- Backend service: `possibleos-backend.service`.
- Frontend service: `possibleos-frontend.service`.
- Frontend dev server listens on port `3099`.
- Backend in this deployment listens on port `8099`.
- Backend health: `GET /health` returns `ok`.
- Use backend port `8099` for REST checks, not the Next.js frontend port.

Useful checks:

```bash
systemctl is-active possibleos-backend.service
systemctl is-active possibleos-frontend.service
curl -sS http://127.0.0.1:8099/health
curl -sS http://127.0.0.1:8099/api/lead-gen/policy/current
curl -sS -I http://127.0.0.1:3099/login
```

## Lead Finder debug shell

`/lead-finder` loads server-authoritative context from
`docs/lead-finder-context/{company,customer,offer,voice}.md`, displays the fixed
recommendation-only job, and stores a user-entered lead direction in the active
context. `POST /api/lead-finder/runs` snapshots the baseline context in
`lead_finder_runs`. `POST /api/lead-finder/runs/{run_id}/steps` idempotently
queues one background reasoning or bounded tool step and immediately returns
its durable id.
The UI polls `GET /api/lead-finder/runs/{run_id}` rather than holding browser
state as the source of truth.

`POST /api/lead-finder/runs/{run_id}/auto-run` enables persisted unattended
execution and queues the next step. The run row stores the enabled flag,
starting step, maximum additional steps, and eventual stop reason. After each
normal persisted transition, the worker locks the run and queues exactly one
next step only when auto-run remains enabled and its budget remains. Completion,
failure, an operator stop, or the bounded step cap ends chaining. The default
cap is 25 additional steps and the API maximum is 100. `POST
/api/lead-finder/runs/{run_id}/auto-run/stop` disables chaining without
interrupting the active LLM-provider or tool call; that step finishes and persists.
Startup recovery requeues both interrupted steps and enabled auto-runs stranded
between two steps, so a browser connection is not required.

Each `lead_finder_steps` row stores the exact user payload, context before,
raw/parsed response, context after, changed paths, model, usage, timing, and
error. `lead_finder_attempts` stores every concrete OpenClaw or direct Responses
API attempt, including retries and interrupted attempts. A row is written before
the provider call, so queued/running work remains observable while the request
is open. A backend restart marks open attempts interrupted and safely requeues
their step. `lead_finder_tool_calls` stores the validated tool name, arguments,
complete result/error, and timing. A backend restart also marks open tool calls
interrupted. Only one active step and at most one tool call are allowed per
transition. Manual debug steps are rejected while auto-run is enabled, so the
manual and unattended paths cannot race for the same next step.

OpenClaw reasoning uses one gateway attempt with a 420-second default timeout
(`LEAD_FINDER_GATEWAY_TIMEOUT_S`) because its baseline context is large. Direct
reasoning uses `LEAD_FINDER_OPENAI_TIMEOUT_S` (300 seconds by default) and one
application-level attempt by default. Neither path duplicates a still-running
request merely because browser polling continues.

The `lead_finder_runs.llm_provider` field selects every future LLM call in the
run. With `openai`, reasoning and web research call the OpenAI Responses API
directly with `gpt-5.6-luna`; with `openclaw`, both use `openclaw/main` through
the loopback gateway. Mission Control search and passage retrieval remain local
non-LLM HTTP tools. Provider changes do not interrupt an active step and apply
when the next step begins.

Each transport maintains independent run continuity. OpenClaw receives a
deterministic, hashed run-scoped `user` value and keeps its local session. Direct
reasoning stores the latest Responses API ID in
`lead_finder_runs.openai_previous_response_id` and passes it as
`previous_response_id` on the next direct reasoning turn. Possible OS persists
the exact request, full provider response JSON, parsed transition, and usage in
`lead_finder_attempts`. Switching away and back resumes that provider's prior
lineage while current run state carries intervening tool evidence.

The first request on either provider uses `context_layout: initial_v2` and
serializes `instruction`, `available_tools`, and deterministic
`stable_context` (job plus baseline files) before `run_state`. Volatile snapshot
timestamps are excluded from the stable block. Later requests use
`context_layout: continuation_v2`; because they target the same provider
conversation, they omit the already-present stable block and tool catalog and append
only current `run_state`. Stateless calls always use the complete initial
layout. Direct requests resend stable Lead Finder instructions because
Responses API instructions are not inherited through `previous_response_id`.
This prevents the large baseline from being repeatedly appended after changing
state while preserving server-authoritative mutable context. The first
request is normally cold; later requests can report a hit in
`usage.prompt_tokens_details.cached_tokens`. The API derives a
normalized `prompt_cache` object for every step and attempt (`hit`, `miss`, or
`unreported`, cached/input token counts, and hit rate). The UI and non-JSON
`lead-finder step` and `lead-finder show` output expose the same metrics. The
legacy stateless `POST /api/lead-finder/step` endpoint deliberately does not
create a shared session.

For an OpenClaw-selected run,
`GET /api/lead-finder/runs/{run_id}/llm-session` resolves the run's hashed
gateway identity through OpenClaw's own `sessions.json` registry and returns
the two on-disk files without parsing or rewriting their records. The canonical
`session_jsonl` is the ordered conversation store. `trajectory_jsonl` is the
runtime trace and includes compiled system prompts, tool definitions, submitted
prompts, model snapshots, and usage. The `/lead-finder` **LLM session (raw)**
view renders either exact JSONL string. These are newline-delimited JSON records,
not one JSON document, and they are deliberately unredacted; the endpoint and
CLI must remain operator-authenticated and their output treated as sensitive.
For readability, the browser splits the selected string by line, parses each
record client-side, labels it by event type/role/sequence/timestamp, and renders
an expandable syntax-highlighted JSON tree. Expand/collapse operations affect
only the DOM presentation. The raw toggle, copy action, API, and CLI continue to
use the byte-identical JSONL supplied by OpenClaw. Direct runs have no local
OpenClaw JSONL; the same UI tab instead renders the persisted Responses API
attempt trace, including the full provider response and latest response ID.
The shared tree also renders Possible OS current context, exact step requests,
before/after snapshots, tool arguments/results, and JSON LLM responses. When a
string field itself contains a valid JSON object or array (for example a gateway
message `content` or assistant `text` field), the browser labels it as a JSON
string and recursively exposes the decoded value as another expandable tree.
The stored string remains unchanged. Every object/array disclosure owns its
open state, so user toggles survive React rerenders and run-status polling;
arrow rotation is derived from that same node state rather than a shared nested
CSS group selector. The readable/raw mode and expand/collapse controls live in
the sticky header inside the JSON viewer so their scope is visually explicit.
The **Run overview** tab is a high-level projection of the same durable records:
it shows each step's summary and reasoning, requested tool and compact result,
next transition, found-lead count, and unattended safety-budget progress. It
does not create a second trace or ask an LLM to summarize the run.
The **Runs** tab projects `GET /api/lead-finder/runs` as a newest-first operator
list with status, selected LLM provider/model, completed-step and found-lead
counts, current direction, next position, and timestamps. Selecting a row loads
the existing run and opens its overview; it does not create or mutate a run.
The equivalent headless surfaces remain `lead-finder runs` and
`lead-finder show <run_id>`.

The discovery adapter is `app/services/mission_control_search.py`. It exposes
only `mission_control.search`, `mission_control.get_passages`, and
`mission_control.index_status`. Mission Control owns transcript chunking, FTS,
local embeddings, and hybrid ranking at `http://127.0.0.1:8001`; Possible OS
never reads `data/mission.db`. Server-side validation caps search results and
passage IDs at 10, rejects unknown fields/tools, and does not expose index
mutation. `GET /api/lead-finder/tools` lists the contract and
`POST /api/lead-finder/tools/execute` provides operator/CLI parity.

`app/services/lead_finder_tools.py` adds two sequenced tools. The agent may call
`web.research_person` only with one named candidate and one to five positive
Mission Control chunk IDs. `app/services/lead_finder_web_research.py` runs
the source-backed web-research skill either directly through the OpenAI
Responses API or through `openclaw/main`, following the same run-wide provider
as reasoning. Direct OpenAI is the default and uses `gpt-5.6-luna` plus the
built-in `web_search` tool. `PUT
/api/lead-finder/runs/{run_id}/llm-provider` changes the provider for all future
LLM calls in the run.
The direct path uses a strict JSON Schema, `store=false`, a stable
`prompt_cache_key`, and 24-hour prompt-cache retention. The API key is read
only from `LEAD_FINDER_OPENAI_API_KEY`; it is never stored on the run or in a
tool result. Both paths normalize the current identity, recent signals, URLs,
contrary evidence, and outreach angles and discard angles without cited URLs.
Each completed tool result persists `_meta` with the actual provider, model,
usage, and provider trace identifiers so the UI and CLI can audit which route
ran. Research remains staged in persisted tool history. On a later click,
`lead_finder.add_researched_lead` must reference the completed web-research
tool-call ID; it then appends the selected research to
`agent_state.working_state.found_leads`. The Found Leads UI tab and
`lead-finder results` read that durable run context. This is intentionally not
a CRM write, and no deduplication is performed.

`POST /api/lead-finder/runs/{run_id}/restart` creates a new step-0 run linked by
`restarted_from_run_id`; it never deletes or rewrites prior history. It inherits
the prior user direction unless overridden, inherits the run-wide LLM provider,
and takes a fresh baseline snapshot.

`POST /api/lead-finder/runs/reset-all` is the explicit destructive reset. In one
database transaction it counts and deletes all Lead Finder runs, cascade-deletes
their steps, provider attempts, and tool calls, and creates one fresh step-0 run using a new
baseline snapshot, supplied user direction, and selected run-wide LLM provider.
It does not touch leads or
any other Possible OS tables. If a deleted step already has a provider request
in flight, its late response is discarded because the persisted step no longer
exists. The UI requires browser confirmation; the CLI requires confirmation or
an explicit `--yes`.

Operator parity:

```bash
bin/possibleos lead-finder context --json
bin/possibleos lead-finder tools --json
bin/possibleos lead-finder mission-search "after-hours intake" --mode hybrid --json
bin/possibleos lead-finder mission-passages <chunk_id> --json
bin/possibleos lead-finder mission-index-status --json
bin/possibleos lead-finder web-research "Jane Operator" --chunk-id <chunk_id> --provider openai --json
bin/possibleos lead-finder start --direction "California PI firms with after-hours intake pain" --provider openai --json
bin/possibleos lead-finder provider <run_id> openclaw
bin/possibleos lead-finder provider <run_id> openai
bin/possibleos lead-finder step <run_id> --json
bin/possibleos lead-finder show <run_id> --json  # raw usage + normalized prompt_cache
bin/possibleos lead-finder llm-session <run_id> --source session
bin/possibleos lead-finder llm-session <run_id> --source trajectory
bin/possibleos lead-finder results <run_id> --json
bin/possibleos lead-finder restart <run_id> --json
bin/possibleos lead-finder reset-all --direction "California PI firms" --provider openai --yes --json
```

The LLM may reason or request one bounded tool per click. Mission Control is the
only discovery source; public web search is available only for a named,
transcript-supported person. The PossibleOS lead database, Reddit, and all
other discovery sources remain unexposed.

## Tests And Validation

Focused backend tests:

```bash
.venv/bin/pytest tests/test_lead_finder.py tests/test_outreach_phi_guard.py tests/test_front_sync.py tests/test_contact_selection.py tests/test_lead_gen_action_planner.py tests/test_sequence_templates.py
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

## Native PI-firm directory (pif_directory_firms)

The lead-gen matching universe historically came from `mission.db` (the Mission
Control SQLite cache), read read-only by `front_sync._load_pif_domain_map`. That
cache is populated by a Mission Control sync that **stopped running in March
2026**, freezing the directory at ~1,711 firms while the live source (emailtag's
`PifInfo`, served at the pif-info API) had grown to ~3,500+ — starving daily lead
selection.

`app/services/pif_directory.py` pulls the directory **directly from emailtag into
Postgres** (`pif_directory_firms`, model `PifFirmRow`), so possibleos owns the
refresh cadence and no longer depends on the dead mission.db sync.

- **Schema:** mirrors every `PifInfo` field — scalars (`firm_name`, `website`,
  `icp_score`, `icp_tier`, …) plus JSONB for `emails`, `phones`, `addresses`,
  `contacts`, `leadership`, `staff`, `contact_profiles`, `research_data`,
  `behavioral_data`, `score_breakdown`, `conversation_ids` — and `raw_json`, the
  untouched API record, so no future field is ever lost.
- **Sync:** `sync_pif_directory()` paginates `GET {PIFSTATS_BASE_URL}/`
  (page_size capped at 100) and upserts by `id`. `pif_directory_sync_loop`
  refreshes daily; it no-ops while the flag is off.
- **Flag:** `PIF_DIRECTORY_NATIVE` (default off). When off, `resolve_firms` reads
  the mission.db map (legacy). When "1", it reads `load_pif_domain_map_from_db()`
  (the native directory; ~2,175 matchable domains vs ~1,141 from mission.db).
  `pif sync` is safe regardless of the flag — warm the table, then cut over.
- **Surface:** REST `POST /api/pif/sync`, `GET /api/pif/status`, and local-only
  `GET /api/pif/sync-status`; CLI `bin/possibleos pif sync | status |
  sync-status`. Completed syncs persist a bounded firm-level ledger with each
  touched firm's created/updated status, website, source timestamp, people
  count, and aliases touched. Aggregate-only legacy runs are reconstructed
  from the exact mirror `synced_at` timestamp when possible.
- **PHI:** `extraction_notes` and conversation context can contain patient names.
  This data is internal-only for selection/targeting; the PHI egress guard
  remains authoritative for anything emitted in outreach.

### Data captured but not yet exploited
possibleos currently uses only `website` + `emails` (domain matching). emailtag
also extracts, per firm: **titled contacts** (`contacts[].title`), **leadership
with bio + LinkedIn**, **per-contact behavioral profiles** (`contact_profiles`:
role, persona, topic_mix, after_hours_ratio, message_count), **firm sender-role
distributions** (`behavioral_data.sender_roles`), and **ICP scores/breakdowns**.
These directly address current selection suppressors (missing firm name, no
mapped persona) and enable behavioral pain-point targeting. Proposed roadmap:
(1) ingest `contacts`/`leadership` as titled, persona-ready `FirmContactRow`s to
lift daily eligible leads; (2) derive persona from `contact_profiles`/titles;
(3) feed `sender_roles`/`topic_mix`/`after_hours_ratio` into the composer for
per-firm pain hooks; (4) order selection by `icp_score`; (5) target `leadership`
decision-makers and wire their LinkedIn into the outreach skills.
