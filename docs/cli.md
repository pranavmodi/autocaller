# Possible OS CLI - Operator's Guide (for humans and AI agents)

This document is the canonical reference for driving Possible OS from the
command line. It is written to be consumed by an AI agent as well as a human
operator: commands, argument schemas, return shapes, failure modes, and
recovery steps are spelled out explicitly.

**Project root:** `/home/pranav/possibleos`
**Entry points (equivalent):**
- `bin/possibleos <command>` — shell wrapper, loads `.env`, prefers `.venv`
- `bin/autocaller <command>` — legacy compatibility alias
- `.venv/bin/python -m app.cli <command>` — direct invocation

All examples below use `bin/possibleos`.

---

## 1. System architecture in one paragraph

Possible OS has two processes: the **daemon** (FastAPI, long-running) and
the **CLI** (short-lived). The daemon receives Twilio webhooks, bridges media
streams, talks to OpenAI Realtime, and runs the dispatcher poll loop. The CLI
is a client that either (a) hits the daemon's loopback REST API for live ops
(`dispatcher start`, `call`, `status`) or (b) reads/writes the Postgres DB
directly for bulk ops (`leads import`, `calls export`, etc.). You cannot place
a call without the daemon running.

```
CLI  ──REST──▶  FastAPI daemon ──▶ Twilio PSTN  ◀────┐
 │                      │                             │
 │                      ├──▶ OpenAI Realtime (voice)  │
 │                      ├──▶ Cal.com (book demo)      │
 │                      └──▶ Postgres (leads, calls)  │
 └─────────────────────(Postgres, bulk reads)─────────┘
```

---

## 2. First-time setup (do this once)

### 2.1 Prerequisites
- Python 3.12 (venv at `./.venv` already exists)
- Postgres reachable at `DATABASE_URL`
- Twilio account (Account SID, Auth Token, an outbound-capable number)
- OpenAI API key with Realtime access
- Cal.com API key + event type id for the demo booking
- A public HTTPS URL that Twilio can reach (ngrok is fine for dev)

### 2.2 Install deps
```bash
cd /home/pranav/possibleos
.venv/bin/pip install -r requirements.txt
```

### 2.3 Configure `.env`
```bash
bin/possibleos config init
```
This walks through every required variable. Or copy `.env.example` → `.env`
and fill in by hand. The daemon won't start without `OPENAI_API_KEY`,
`DATABASE_URL`, and (for real calls) the four Twilio vars + `ALLOW_TWILIO_CALLS=true`.

### 2.4 Run DB migrations
```bash
.venv/bin/alembic upgrade head
```
This creates the `patients`, `call_logs`, `system_settings` (and legacy) tables.

### 2.5 Verify
```bash
bin/possibleos doctor
```
Every row must be `✓` before attempting a live call. See §8 for interpreting
each row.

---

## 3. Top-level command reference

```
possibleos <command> [options]

Commands
  serve          Start the FastAPI daemon (foreground).
  call           Place a call immediately (bypass dispatcher).
  status         One-shot system status summary (dispatcher + current call).
  doctor         Validate env + connectivity (db, Twilio, OpenAI, Cal.com).
  leads          Manage leads (import, list, show, add, remove, sync-mission).
  calls          Inspect call history + transcripts + judge.
  dispatcher     Control the auto-dispatcher (start, stop, batch, status, clear-active).
  front          Sync Precise Front contacts/activity and inspect warm signals.
  config         Config / .env wizard + inspection.
  system         Global on/off — master kill switch.
  mock           Mock-mode toggle (redirect all Twilio calls to a mock phone).
  allowlist      Manage allowed_phones (phone allowlist).
  followups      GTM follow-up queue — calls awaiting action.
  ideas          Simple future product, marketing, and GTM idea capture.
  listening      Mission Control mindset brief, insights, sources, and prep.
```

Every command accepts `--help`. Exit code is `0` on success, `1` on any error
(network, validation, missing resource).

### New-command reference (v1.1)

| command | purpose |
|---|---|
| `pif sync [--full] [--limit N] [--restart]` | Pull EmailTag firm-intel v2 profiles into Postgres (`pif_directory_firms`) and aliases into `firm_intel_aliases`. Delta sync uses `firm_intel_sync_state.last_updated_since`; `--full` ignores the watermark; `--limit` is for smoke runs such as `pif sync --limit 20`. Interrupted full crawls save a resume point and continue from it on the next run (the upstream feed tolerates a bounded number of requests per session); `--restart` discards the saved point. |
| `pif status` | Show native firm-intel mirror state: total firms, profile-source counts, alias count, watermark, last sync summary, and EmailTag v2 `/health` passthrough. |
| `pif resolve <domain\|email\|url\|legacy_pif_id>` | Resolve locally through `firm_intel_aliases` and mirrored websites; if no local hit, fall back to EmailTag v2 `/firms/resolve`. Prints `firm_id`, `firm_name`, and source. |
| `pif show <firm_id\|domain>` | Print the mirrored v2 profile summary for a firm: name, website, metro, ICP tier, warm score, decision-makers with emails, and vendor stack. Local-only; no upstream HTTP. |
| `pif ingest-contacts` | Populate `firm_contacts` from the synced directory's titled `contacts[]` + `leadership[]` (then map personas). Local-only, no API calls. This is the lead-supply unlock: emailtag's named, titled contacts give personas + firm names for free, lifting daily eligible leads (verified: selection 11 → full 20, decision-maker-weighted). Runs automatically after each `pif sync` when `PIF_DIRECTORY_NATIVE=1`. |
| `decisions add "<title>" --area <area> [--why … --decision … --status … --refs …]` | Append a formatted, auto-id'd entry to today's (UTC) decision log `docs/decisions/<date>.md` (creates it if new; append-only; no daemon needed). Areas: lead-gen, deliverability, data-arch, website, infra, process, product. Mandated by the Decision-log rule in `CLAUDE.md`; format in `docs/decisions/README.md`. |
| `decisions today` / `decisions areas` | Print today's decision-log file / list the area taxonomy. |
| `system on \| off \| status` | Master kill switch. `off` blocks all calls regardless of dispatcher state. |
| `mock on <phone> \| off \| status` | Redirect every Twilio call to `<phone>` for safe testing. |
| `allowlist list \| add <phone> \| remove <phone> \| clear \| set-from-leads [--state=CA --dm-only --limit=20]` | Manage `allowed_phones`. `set-from-leads` populates it from the top-N priority-sorted leads in the DB. |
| `dispatcher batch <N>` | Start the dispatcher with an auto-stop after N calls placed. |
| `dispatcher clear-active` | Hang up the live Twilio call (if any) and clear the active-call marker. Used by the UI "End call" button. |
| `dispatcher cooldown [<seconds>]` | Get (no arg) or set the wait applied after a call ends before the dispatcher places the next one. Persisted in `system_settings.dispatcher_settings.cooldown_seconds`. |
| `ivr status\|on\|off` | Toggle LLM-driven phone-tree navigation. When ON, hitting an IVR hands control to `IVRNavigator` (classifies voicemail-vs-menu, picks a digit, presses via Twilio DTMF, repeats up to 3 hops / 60 s). When OFF, legacy behavior (hang up on first menu prompt) stays. Per-call state lives on `call_logs.ivr_detected` / `ivr_outcome` / `ivr_menu_log`. |
| `leads set-language <id> en\|es` | Set a lead's outbound-call language. Controls which prompt template (`SYSTEM_PROMPT_TEMPLATE` vs `SYSTEM_PROMPT_TEMPLATE_ES`) and which first-word seed ("Hello?" vs "¿Bueno?") the voice backend uses. `prompt_version` on the call log is stamped with a `-en` / `-es` suffix for A/B analysis. |
| `leads list --language=es` | Filter lead list by language. |
| `calls judge <call_id>` | Run the LLM judge on one call (scores 0-10, assigns GTM disposition). |
| `calls judge --all-pending` | Backfill-judge every un-judged completed call. ~$0.02 each with gpt-4o-mini. |
| `followups list [--action=... --owner=... --disposition=... --within=14]` | Show calls that need human or automated follow-up, sorted by due date. |
| `followups show <call_id>` | JSON focus view for a single follow-up. |
| `followups send-voicemail <call_id> [--dry-run]` | Send the voicemail / no-reach follow-up email for one call. Gated by `ALLOW_VOICEMAIL_EMAIL=true`. Resolves recipient from `captured_contacts` then `patients.email`. |
| `followups backfill-voicemails [--since-days=7 --limit=50 --live]` | Batch-send pending voicemail / no-reach follow-up emails. Default is `--dry-run`; pass `--live` to actually send. Also gated by `ALLOW_VOICEMAIL_EMAIL`. |
| `leads sync-mission [--tiers=A,B --dm-threshold=5]` | LLM-driven import of PI-firm contacts from Mission Control. |
| `voice status` | Show the current default realtime voice backend (openai or gemini) + model. |
| `voice openai [--model=…]` / `voice gemini [--model=…]` / `voice set <p> [--model=…]` | Switch the default backend for subsequent calls. Stored in DB. |
| `call <lead_id> --voice=openai\|gemini` | Per-call override: pin this specific call to a provider regardless of the default. |
| `calls list --provider=openai\|gemini` | Filter history by which backend handled each call. |
| `carrier status` | Show both telephony carriers (Twilio + Telnyx): masked SID/key, account name + type, reachability, from-number status, live balance. Marks whichever is the current default. Also visible on the `/system` page with a switch button. |
| `carrier twilio \| telnyx \| set <name>` | Change the default telephony carrier. Persisted in `system_settings.default_carrier`. Affects all new calls unless overridden per-call. |
| `call <lead> --carrier=twilio\|telnyx` | Per-call carrier override (highest precedence). |
| `calls takeover <call_id> [--off]` | Flip human-takeover on a live call: mutes AI audio to Twilio, cancels the in-flight response, and lets the UI pipe the operator's browser mic into the call via `/ws/listen/{call_id}`. Pass `--off` to hand back to the AI. Also available as a button on the `ActiveCallOverlay` in any frontend page. Audio path: browser mic → AudioWorklet (`/operator-mic-worklet.js`, 48kHz→8kHz µ-law, 20ms frames) → listener WS as `{type:"inbound_audio",payload:<base64>}` → `TwilioMediaBridge.inject_inbound_audio` → Twilio `media` event. |
| `env` setup for carriers | **Twilio:** `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, optional `TWILIO_ACCOUNT_LABEL`. **Telnyx:** `TELNYX_API_KEY` (V2 bearer), `TELNYX_FROM_NUMBER`, optional `TELNYX_ACCOUNT_SID` (defaults to `"default"`), optional `TELNYX_ACCOUNT_LABEL`. Both carriers share the `ALLOW_TWILIO_CALLS=true` safety gate. |
| `prompts show` / `prompts list` | Display the active prompt style + version. Two parallel styles exist: `current` (rules-heavy, `v1.61`) and `minimal` (intent-first, `v2.0-minimal`). Switch by setting `PROMPT_STYLE=current\|minimal` in `.env` and restarting the backend. Default = `current`. |
| `prompts preview [--style=current\|minimal] [--lead-name=... --firm=... --state=...]` | Render the full system prompt against a sample lead — eyeball what each style sends to the model without placing a live call. |
| `email status` | Show email transport (Resend vs SMTP), sender address, allowed sender overrides, default recipient, BCC, reply-to, and the `ALLOW_VOICEMAIL_EMAIL` gate. Sensitive values masked. |
| `email test [--to=... --from=... --subject=... --body=...]` | Send a plain test email end-to-end. Recipient defaults to `EMAIL_NOTIFICATION_RECIPIENT`; sender defaults to `SMTP_FROM_EMAIL` and can be overridden by a configured/allowed address. Verifies Resend/SMTP credentials without firing a templated follow-up. |
| `email send-onepager --to=... [--name=... --firm=... --note=... --rep-name=... --rep-company=... --rep-email=...]` | Manually fire the post-call one-pager template (same as the AI's `send_followup_email`). Rep fields default to `SALES_REP_*` env. |
| `email send-vm-followup --to=... [--first-name=...] [--no-vm]` | Manually fire the VM / no-reach follow-up template against an arbitrary address (no `call_id` needed — useful for previewing copy). Same `ALLOW_VOICEMAIL_EMAIL` gate as the automated path. `--no-vm` switches to the "tried to reach you" subject/opener. |
| `email send-consult --to=... --name=... --slot="Wed Apr 30 at 2:00 PM PT" [--firm=... --notes=...]` | Manually fire the consult-booking confirmation (same template Cal.com booking flow uses). Includes the Google Meet link from `CONSULT_MEET_URL`. |
| `comms list [--firm=<pif_id> --channel=call\|voicemail\|sms\|email --since=7d --status=... --q=... --limit=N --raw]` | Cross-firm or per-firm outbound communications feed. Unions `call_logs` (channel = `call` or `voicemail` based on `voicemail_left`), `email_logs`, and `sms_logs` by timestamp. Mirrors the `/comms` UI page. `--raw` prints JSON instead of a table. |
| `comms show <channel-prefixed-id>` | Print one communication as JSON. ID format: `call:<call_id>` (covers voicemail too), `email:<id>`, `sms:<id>`. |
| `contacts backfill [--limit=N]` | Pull leadership rosters from PIF Stats + possibleos patient DM rows into `firm_contacts`. Idempotent. Run once before using `sequences start`. |
| `contacts list [--firm=<pif_id>] [--limit=N]` | List firm_contacts rows. Without `--firm`, walks across firms. |
| `front sync [--full] [--max-calls N] [--json]` | Budgeted read-only Precise Front sync: contacts, inbox activity metadata, offline firm resolution, and warm-score refresh. Hard-caps API calls and persists cursors/watermarks. |
| `front status [--json]` | Show Front sync health, cursors, watermarks, table counts, funnel counts, day-over-day deltas, and timing feed data used by `/front`. |
| `front contacts [--firm=<pif_id> \| --domain=<domain> --q=<text>] [--limit=N] [--json]` | List synced Front contacts with matched pif_id, masked email display, warm score, and tech signals. |
| `front warm-batch --domains a.com,b.com [--name=...] [--json]` | Create a recommended lead-gen batch directly from selected Front-warm domains. Items use `reason_json.basis = "front-warm"` and stay pending for review in `/lead-gen`. |
| `research firm <domain-or-pif> [--staff/--no-staff] [--behavior] [--poll] [--json]` | Queue PIF Stats firm research for one warm-list domain or PIF ID. Uses only safe task-creating POSTs, hard-capped at 30 per run with >=2s spacing. `--behavior` also queues behavior analysis. |
| `research warm [--top=50] [--kinds=research,staff] [--timeout=1800] [--json]` | Walk the Front warm list by warm score, skip already researched firms, queue research up to the POST budget, poll for completion, upsert titled contacts, sync behavior JSON, and map personas. |
| `research status [--tasks] [--json]` | Show matched-firm research coverage, staff/behavior coverage, task status counts, and optionally open task rows. |
| `research sync [--json]` | Poll queued/running research tasks and upsert completed results without queueing new production work. Use to resume after a prior warm run timed out. |
| `personas map [--pif=<id>] [--json]` | Fill `firm_contacts.persona`, source, and confidence from research/title keywords or functional email prefixes. Idempotent and never lowers confidence. |
| `personas show <domain-or-pif> [--json]` | Print a firm's contacts with title, mapped persona, source, and confidence. |
| `composer-ab variants` | List composer skill variants (subject-line experiment arms) with active state and allocation weight. |
| `composer-ab assign <contact_id>` | Preview the deterministic (rendezvous-hash) variant assignment for a contact. |
| `composer-ab report [--days 60] [--json]` | Persona-blocked A/B report: sends/opens/replies per arm with beta-binomial P(beats baseline), verdict gated at 40 sends/arm and 90% probability. Warns when Resend opens are not flowing. |
| `front competitors rebuild [--json]` | Recompute local firm-vs-firm competition features and edges from cached Mission Control SQLite plus `front_firm_activity`. No Front API calls and no LLM calls. |
| `front competitors summary [--json]` | Show competitor graph coverage: firms with features/metros, edge count, tier distribution, top metro counts, and last rebuild time. |
| `front competitors show <domain-or-name> [--limit=N] [--json]` | Show who competes with one firm, including score, neighbor name/domain/metro, and one-line evidence. |
| `front competitors search <q> [--limit=N] [--json]` | Search any firm with local competitive features by firm-name or domain substring, including edge count and warm-list status. |
| `front competitors graph <domain-or-name> [--depth=1] [--json]` | Print a firm's competitive ego network: node/link counts plus top edges, or raw graph payload for scripts with `--json`. |
| `sequences preview <contact_id>` | Render the configured dynamic email sequence for one contact against their actual personalization data. Read-only. |
| `sequences start <contact_id>` | Start the configured sequence for one contact. Idempotent — second start returns 409 with current state. Sends gated by `ALLOW_SEQUENCE_SEND=true`. |
| `sequences list [--status=active\|paused\|completed]` | List sequence rows + which step each is on. |
| `inbound status` | Show whether Zoho IMAP inbox reading is configured. Sensitive values masked. |
| `inbound poll [--limit=N --classify --mark-seen]` | Poll Zoho IMAP for unread/recent replies, store inbound rows, match lead-gen contacts, and create observations. |
| `inbound list [--matched=yes\|no]` | List stored inbound email messages. |
| `todos list [--area=lead-gen] [--status=not_started] [--json]` | Show the DB-backed editable project backlog. |
| `todos add <title> [--area=lead-gen --status=not_started --body=... --source-url=...]` | Add a DB-backed todo. |
| `todos update <id> [--title=... --status=done --body=... --clear-source-url]` | Edit a DB-backed todo. |
| `todos delete <id>` | Delete a DB-backed todo. |
| `ideas list [--json]` | List saved future product, marketing, GTM, and ops ideas. Reads rows stored in the DB-backed todo table under `area=ideas` and legacy `idea:*` areas. |
| `ideas add "..." [--json]` | Save a simple future idea. Use `ideas add - < idea.txt` or pipe stdin for multiline text. |
| `ideas edit <id> "..." [--json]` | Replace the text for a saved idea. Use `ideas edit <id> - < idea.txt` for multiline text. |
| `lead-gen email-agent-slice [--limit=3 --composer-variant=... --approval-ready --batch=<batch_id> --json]` | Select eligible contacts, collect bounded internal evidence, compose drafts with the Possible Minds email composer skill, and create durable `send_email mode=lead_gen` actions for review or policy checks. With `--batch`, skip selection and compose for an existing batch's pending undrafted items (operator- or agent-curated lists, e.g. Front-warm shortlists). |
| `lead-gen visibility-report [--batch-item=<id> \| --firm-name=... --domain=...] [--market=...] [--dry-run] [--force] [--json]` | Ensure an AI Search Visibility report exists through the `ai-visibility` CLI. Existing scanned reports are reused by domain/firm unless `--force` is passed. With `--batch-item`, caches a compact report package at `reason_json.ai_visibility_report` for the `ai-visibility-report` composer variant. |
| `lead-gen daily-run [--dry-run] [--force] [--variant=<key>] [--json]` | Run the deterministic daily lead-selection pipeline now. It gates on system enabled, active policy budget, weekday, and deliverability health; refreshes stale Front-derived signals without Front API calls; queues bounded research; maps personas; creates a persona-mixed batch; composes drafts; and schedules `waiting_for_approval` lead-gen email actions in the PT morning window. `--dry-run` performs no writes, no external research calls, no actions, and no WhatsApp. `--variant=<key>` pins one composer skill variant on **every** email in the run — first-touch and follow-up — overriding the per-item default/A-B (must be an active variant; see `composer-ab variants`). Without it, first-touch uses `LEAD_GEN_FIRST_TOUCH_VARIANT` (default `review-evidence`), follow-ups use the per-contact A/B unless `LEAD_GEN_FOLLOW_UP_VARIANT` is set. |
| `lead-gen top-up --count N [--variant=<key>] [--json]` | Add `N` fresh first-touch sends to today's daily run without recomposing the existing batch. It excludes every contact already batched for that run date, creates a sidecar `Daily run <date> top-up` batch, composes with the optional active variant, and schedules/auto-approves through the same daily-run send-action path. |
| `lead-gen daily-status [--date YYYY-MM-DD] [--json]` | Show the checkpointed daily-run stage table, status, batch id, counts, and errors. Partial runs resume incomplete stages when `daily-run` is called again. |
| `lead-gen backfill-consult-links [--scope today\|all] [--dry-run] [--json]` | Replace the bare `getpossibleminds.com/consult` link with a per-recipient tracked `/c/{code}` short link in **unsent** lead-gen sends, then re-hash + re-approve each at its existing `scheduled_for` slot (so the scheduler still sends the exact draft). Mirrors the audit link's per-recipient attribution; clicks log an `AuditLinkClickRow` (`kind=consult`, `source=consult_email`) + a `link_clicked` observation (`channel=consult`) and 302 to the consult page. `--scope today` = the live daily batch; `--scope all` = every unsent (approved/waiting) lead-gen send. Idempotent (rows already carrying `/c/` are skipped). New composes get the tracked link automatically. |
| `lead-gen throughput [--date YYYY-MM-DD] [--json]` | Show the daily send-throughput funnel: selected, with review evidence, composed, scheduled/sending today, sent today, held firms, auto-send state, shortfall, and the current blocker. |
| `lead-gen daily-enable` / `lead-gen daily-disable` | Flip the persisted `daily_run_enabled` flag. The daemon loop is wired on boot but defaults disabled and no-ops until an operator enables it. |
| `lead-gen observations [--since=7d --type=<event_type> --contact=<contact_id> --json]` | List automatic lead-gen observations with batch/contact/item linkage. Includes sends, failures, replies, clicks, bookings, call dispositions, cancellations, and reschedules. |
| `lead-gen observations summary [--since=7d --json]` | Count observations by event type for the weekly learning KPI / qualified-engagement readout. |
| `aiaudit link --contact <contact_id> [--source ai_audit_signature\|ai_audit_email]` | Print a contact-attributed AI Audit redirect URL using `OUTREACH_PUBLIC_BASE_URL` and signed by `AIAUDIT_LINK_SECRET`. |
| `aiaudit clicks [--since 7d] [--limit 50]` | List recent `audit_link_clicks` rows and matching AI Audit `link_clicked` observations. |
| `visibility-clicks [--days 7] [--limit 50]` | List recent AI Visibility report-link click attribution from `audit_link_clicks`, joined to contact and firm. |
| `leads warm-list [--limit=20] [--json]` | Print the top Front-warmed firms with named contacts that have not yet been emailed. Use after `front sync` for the daily warm-list workflow. |
| `actions list [--status=approved --type=send_approved_lead_gen_draft --scheduled --json]` | List durable Possible OS action execution records. `--scheduled` shows only future approved scheduled actions ordered by `scheduled_for`; the normal list header includes the pending scheduled count. |
| `actions show <action_id> [--json]` | Show one action with its append-only event timeline. |
| `actions scheduler-status [--json]` | Show whether the daemon scheduled-action loop is running, last tick time, pending scheduled count, and due count. |
| `actions policy-check <action_id> [--actor=operator --json]` | Run the reusable policy checker without executing the action. For lead-gen email actions this includes `no_patient_data_in_outreach`, a deterministic + LLM PHI egress guard on the final rendered subject/body. |
| `actions execute <action_id> [--actor=operator --json]` | Execute one policy-approved action through its narrow executor. |
| `actions cancel <action_id> [--reason=... --actor=operator --json]` | Cancel an action that is still `waiting_for_approval` or `approved`, including scheduled sends. Refuses terminal/running actions and appends `action_cancelled` to the timeline. |
| `actions reschedule <action_id> --at "10:30 PT" [--actor=operator --json]` | Move an approved scheduled action to a new future ISO/PT time. Prints old -> new in Pacific and UTC and appends `action_rescheduled`. |
| `actions execute-approved-lead-gen [--limit=1 --actor=operator --json]` | Execute already-approved `send_email mode=lead_gen` actions through the durable policy gate. This is the narrow action the master agent may use when approved-send automation is enabled. Successful sends link the action result to the `email_logs` row, transport, message id, and log status. |
| `actions send-approved-lead-gen-draft --item=<batch_item_id> --subject=... --body=... [--approved-by=operator] [--at "09:30 PT"] [--no-execute]` | Create and optionally execute the first high-risk action slice: an exact approved lead-gen email draft sent through the existing Zoho-backed lead-gen path. With `--at`, stores `scheduled_for`, runs policy check, does not execute, and prints PT plus UTC. |
| `actions send-email --mode=test --to=<email> --subject=... --body=... [--approved-by=operator --from=... --at "2026-06-11T09:30:00-07:00" --no-execute --json]` | Create, policy-check, and optionally execute a regular durable test email action. With `--at`, creates an approved scheduled action and never sends immediately. |
| `actions send-email --mode=lead_gen --to=<email> --subject=... --body=... --contact=<contact_id> --item=<batch_item_id> [--pif=<pif_id> --firm=... --approved-by=operator --at "09:30 PT" --no-execute --json]` | Create, policy-check, and optionally execute an exact approved lead-gen email action. Policy verifies recipient/contact match, approval hashes, consult link, no patient data in outreach, Zoho transport, no suppression, and no prior successful send for the same item/recipient. With `--at`, the daemon sends when due and expires stale actions more than 24h late. |
| `actions send-test-email --to=<email> [--subject=... --body=... --approved-by=operator --from=... --no-execute --json]` | Convenience alias for `actions send-email --mode=test`. Use the regular email action family for master-agent execution-path tests instead of free-form email shell commands. |
| `lead-gen edit-draft <batch_item_id> [--at "10:30 PT"] [--editor/--no-editor] [--execute] [--json]` | Open the current `agent_draft` in `$EDITOR`, save it back to the queued action, and keep the batch item's UI draft fields approved/in sync. If a live scheduled action exists, edits update it instead of creating a duplicate; otherwise the command creates a new approved draft action. |
| `listening brief [--version N]` | Print the Mission Control mindset brief markdown from `http://127.0.0.1:8001/api/listening`. |
| `listening search "<q>" [--type T] [--who W] [--limit N]` | Search extracted listening insights by query, type, and buyer persona. |
| `listening quotes --cluster <cluster> [--limit 5]` | Show direct quotes for one listening insight cluster. |
| `listening sources` | Show listening source name, kind, last poll time, and computed stale flag. |
| `listening prep <firm-or-name>` | Combine local `patients`/`firm_contacts` context, top matched insights, and one gateway call into a pre-call persona, objections, and vocabulary one-pager. |
| `agents status [--json]` | Show the Possible OS master-agent heartbeat configuration, objective status, and last heartbeat result in the current backend process. |
| `agents config [--interval-seconds=300] [--enabled/--disabled] [--auto-send-approved-lead-gen\|--no-auto-send-approved-lead-gen --auto-send-limit=1 --json]` | Update persisted master-agent heartbeat settings. The approved-send toggle lets heartbeat execute exact approved lead-gen email actions through the policy gate. |
| `agents heartbeat [--json]` | Run one master-agent heartbeat tick immediately. V1 reads `soul.md` as protected read-only context, records traces, checks active subagent tasks, marks stale workers, and, only when enabled, executes already-approved lead-gen email actions. |
| `agents list [--status=all --agent=ResearchScoutAgent --limit=100 --json]` | List durable master/subagent task packets. |
| `agents show <task_id> [--json]` | Show one subagent task with recent lifecycle events and reports. |
| `agents create --agent=... --title=... --objective=... [--priority=50 --risk=low]` | Create a minimal durable subagent task packet. |
| `agents create-research-scout [--json]` | Create the first safe web-learning task for ResearchScoutAgent. It is proposal-only and must not edit code, send email, or modify mailboxes. |
| `agents create-systems-health [--json]` | Create the next safe SystemsHealthAgent observation/delegation task. The first worker slice is read-only observe/report. |
| `agents run-research-scout [--task=<task_id> --json]` | Run one ResearchScoutAgent task now. Fetches official sources where reachable, writes `docs/learning-notes/...`, and creates an `agent_reports` row. |
| `agents run-systems-health [--task=<task_id> --json]` | Run one SystemsHealthAgent read-only health observation task now. Reads bounded service status, recent journals, `/health`, recent traces, and recent agent events; writes an `agent_reports` row. It does not edit code, restart services, send mail, or modify external state. |
| `agents capabilities [--refresh] [--no-probe] [--json]` | List or refresh the master-agent capability registry. Refresh runs only safe probes; actionful capabilities are declared without execution. |
| `agents goals [--status=active --json]` | List durable adaptive master-agent goals synthesized from queue state, capabilities, reports, and current context. |
| `agents set-goal "..." [--why=... --next-action=... --success-metric=... --expires-hours=24 --json]` | Set a manual active master-agent goal that heartbeat respects until expiry instead of immediately synthesizing over it. |
| `agents set-status <task_id> <status> [--message=...]` | Set a subagent task status. |
| `agents task-heartbeat <task_id> --agent=... [--message=... --status=running]` | Record a heartbeat/progress ping from a subagent. |
| `agents report <task_id> --agent=... --summary=... [--status=reported]` | Attach a structured report-back artifact to a subagent task. |
| `agents events [--task=<task_id> --limit=100]` | List recent master/subagent lifecycle events. |
| `agents reports [--task=<task_id> --limit=100]` | List recent subagent reports. |

Heartbeat status uses `app/skills/master-agent-status/SKILL.md`,
`soul.compact.md`, and the shared OpenClaw gateway client when available. The
skill is the stable status-writing behavior; `soul.compact.md` is passed as
compact constitutional guidance near the beginning of the LLM payload; volatile
task, report, event, and config state comes after it. Full `soul.md` remains
protected and is included only as metadata/hash unless a deeper strategic task
explicitly needs it. If the gateway fails, the heartbeat still completes with a
deterministic fallback status and records the gateway error in the event
metadata.

When the board is idle, the heartbeat may auto-delegate one safe internal next
slice as a queued task. Current V1 auto-delegates the SystemsHealthAgent
log-observation/delegation task once. The SystemsHealthAgent worker now supports
the first read-only slice: observe and report only. It reads bounded local
health/log/trace sources, redacts likely secrets, and writes a report. It does
not edit code, restart services, send emails, place calls, or modify external
state.

The heartbeat now creates a durable adaptive goal in `master_goals` on each run.
It filters prior `master_heartbeat_completed` prose out of `recent_events` and
passes a compressed `recent_heartbeat_summary` instead, reducing status echo.
It also adds `queue_analysis` so old queued work is visible as stale-by-age or
blocked-by-missing-runner instead of being treated as indefinitely ready.

Default lead-gen batches now use `possible_minds_dynamic`. It treats steps as
objectives and composes the actual email at send time with
`app/skills/possible-minds-lead-email-composer/SKILL.md`. In the Lead Gen UI,
the operator no longer selects a strategy; the composer skill chooses the
per-contact angle from context and returns its rationale with the draft. Fixed
templates such as `precise_records_audit` remain CLI/API fallback paths.

Lead-gen batch creation now builds a daily action plan, not only a cold-start
contact list. The planner first allocates the fixed daily budget to active
conversation actions such as inbox replies, pending draft approvals, and due
follow-ups, then fills remaining capacity with new first-touch contacts.
New first-touch contacts are ranked by an explainable contact-selection scorer
that stores persona, firm-fit, relationship, email-quality, history, score
breakdown, suppressions, and policy version on each selected batch item.
Reply/draft actions continue through the operator action center. When a batch is
approved with queueing enabled, every queueable new start or due follow-up
immediately creates an operator action and pauses the sequence as
`awaiting_operator_send_approval`. Draft composition is lazy: opening the action
center item generates the actual email draft and rationale, and the email sends
only after the operator reviews/edits/clicks send. The daily send budget is
persisted on the active lead-gen policy and can be saved from the Lead Gen UI
before generating today's list.

The smallest master-agent lead-gen slice is:

```bash
bin/possibleos lead-gen email-agent-slice --limit 3 --approval-ready
```

That command creates a normal lead-gen batch, stores research evidence and an
`agent_draft` on each selected batch item, and creates durable
`send_email mode=lead_gen` actions in `waiting_for_approval`. It does not send
email. For no-send policy validation of an exact approved action, run:

```bash
bin/possibleos lead-gen email-agent-slice --limit 3 --approve-actions --policy-check-first-action --json
```

For the AI Search Visibility outbound motion, generate or reuse the report
before composing the email. The bridge calls the `ai-visibility` CLI and will
not generate a duplicate when a scanned report already exists for the firm
domain:

```bash
bin/possibleos lead-gen visibility-report --batch-item <batch_item_id>
bin/possibleos lead-gen email-agent-slice --batch <batch_id> --composer-variant ai-visibility-report
```

Use `--dry-run` on `visibility-report` only for mock/test reports, and
`--force` only when you intentionally want a fresh scan.

---

## 4. Daemon lifecycle

### `possibleos serve`
Starts the FastAPI daemon in the foreground on `BACKEND_PORT` (default 8000).
Runs the dispatcher, mounts the Twilio webhooks at `/api/twilio/*`, and exposes
the REST API.

```bash
bin/possibleos serve                 # foreground, production log level
bin/possibleos serve --reload        # auto-reload on code change (dev only)
bin/possibleos serve --port 9000     # bind on a different port
```

**For AI agents / unattended operation:** Run the daemon under a supervisor
(systemd, tmux, or `nohup`). The CLI calls below assume the daemon is reachable
at `http://127.0.0.1:${BACKEND_PORT:-8000}`.

Example `tmux` pattern:
```bash
tmux new -d -s possibleos 'cd /home/pranav/possibleos && bin/possibleos serve'
tmux capture-pane -t possibleos -p | tail -20   # peek at logs
```

### Stopping the daemon
```bash
tmux kill-session -t possibleos
# or: pkill -f 'uvicorn app.main:app'
```

Shutdown is clean — the dispatcher stops, any in-flight call is ended with
outcome `FAILED` (the caller on the other end will hear a hangup).

---

## 5. Lead management

### 5.1 CSV import (`possibleos leads import`)

```
possibleos leads import <csv_path> [--source=csv] [--dry-run]
```

- `<csv_path>`: existing, readable CSV file.
- `--source` (string, default `csv`): tag stored on each row's `source` column. Useful for tracking lead provenance (e.g. `--source apollo_2026_04`).
- `--dry-run` (flag): parse + validate only. No DB writes. Prints parsed counts.

**CSV schema** (headers are case-insensitive; column order doesn't matter):

| column          | required | notes |
|-----------------|----------|-------|
| `phone`         | ✓        | Any format; normalised to E.164 (`+1XXXXXXXXXX`). Rows with unparseable phones are skipped. |
| `name`          | ✓        | Attorney's full name. |
| `firm` or `firm_name` | — | Firm / practice name. |
| `state`         | —        | 2-letter US state. Used for per-state calling-hours gate + slot timezone. |
| `practice_area` | —        | e.g. `personal injury`. |
| `email`         | —        | Cal.com invitee + follow-up email. |
| `title`         | —        | e.g. `Managing Partner`. Used for decision-maker detection (see §9). |
| `website`       | —        | |
| `tags`          | —        | Pipe-separated (e.g. `high-volume-mva\|solo`). |
| `notes`         | —        | Free-form pre-call research. |
| `id` or `lead_id` | —      | If present, used as primary key (enables idempotent re-imports). Otherwise auto-generated as `LEAD-NNNNNN`. |

**Example CSV:**
```csv
name,firm,phone,state,practice_area,email,title,tags,notes
Jane Rothstein,Rothstein & Associates,(212) 555-0198,NY,personal injury,jane@rothsteinlaw.com,Managing Partner,high-volume-mva,"Referral from bar directory"
Paul Chen,Chen Law Group,415-555-0144,CA,pi + workers comp,paul@chenlaw.legal,Partner,solo,
```

**Behaviour:**
- Rows with an existing `id` → **updated** (upsert).
- Rows with a new `id` (or none) → **inserted**.
- Invalid rows (missing phone or name) → **silently skipped** and counted.
- `priority_bucket` recomputed on read: decision-maker title + never-called = bucket 1 (highest).

**Return:** prints `Imported N new, updated M.` on stderr. Exit code `0` iff
the import committed.

### 5.2 List (`possibleos leads list`)
```
possibleos leads list [--state=CA] [--limit=50]
```
Table columns: `id, name, firm, state, phone, title, attempts, last_outcome`.
Sorted by `priority_bucket` then `updated_at desc`.

### 5.3 Show (`possibleos leads show <lead_id>`)
Prints the full row as JSON (pretty-printed by Rich). Exit code `1` if not
found — agents should check the exit status, not parse the error string.

### 5.4 Add / remove
```
possibleos leads add --name "Jane Doe" --phone 555... [--firm ...] [--state CA] [--email ...] [--title Partner] [--practice-area "personal injury"]
possibleos leads remove <lead_id>
```

---

## 6. Placing calls

There are two ways a call goes out: **manually** (single-shot) or **dispatched**
(auto polling loop).

### 6.1 Manual single-shot (`possibleos call`)

```
possibleos call <lead_id> [--mode=twilio|web]
```

- `--mode=twilio` (default): real PSTN call via Twilio. **Requires** `ALLOW_TWILIO_CALLS=true` **and** the lead's phone in `allowed_phones` (until you remove the allowlist).
- `--mode=web`: browser-voice mode. Needs a connected voice WS client. In a headless deployment this is effectively unused — retained for dev testing.

The daemon must be running. Returns the created `call` object as JSON (shape described in §7.2).

**Failure responses:**
| exit | cause | fix |
|------|-------|-----|
| 1    | HTTP 400 `patient_id is required` | pass a valid lead id |
| 1    | HTTP 409 `Call could not be started` | another call in progress, OR `ALLOW_TWILIO_CALLS` gate, OR lead not in `allowed_phones`. Check `possibleos status` and daemon logs. |
| 1    | network error | daemon not running — `possibleos serve` |

### 6.2 Auto-dispatched (`possibleos dispatcher …`)

```
possibleos dispatcher start    # enable polling (kicks off first call if eligible)
possibleos dispatcher stop     # pause — in-flight call continues until natural end
possibleos dispatcher status   # JSON: state, last decision, running flag, config
```

The dispatcher polls every `dispatcher_settings.poll_interval` seconds (default
10). On each tick it evaluates, in order:

1. `system_enabled` (DB setting).
2. Operator-wide `business_hours` (DB setting, enforced in the `business_hours.timezone`).
3. No `has_active_call`.
4. Inter-call `cooldown_seconds` (default 120) elapsed since the last ended call.
5. Candidate must be within **its state's** calling window (09:00–17:00 local
   Mon–Fri by default — configured in `per_state_hours`).
6. Candidate `attempt_count < max_attempts` and `last_attempt_at` older than `min_hours_between` (default 6h).

If all gates pass, the dispatcher picks the highest-priority eligible lead and
starts a call. On call end, the lead's `attempt_count` increments and
`last_outcome` is set — the lead won't be re-tried until cooldown expires.

**Inspecting a dispatcher decision:**
```bash
possibleos dispatcher status | jq .recent_decisions
```
Each entry has `{timestamp, decision, detail, state}`. Common `decision` values:
`started`, `stopped`, `blocked`, `no_candidate`, `starting_call`, `call_started`,
`call_ended`, `dispatch_timeout`, `start_failed`.

---

## 7. Call history + outcomes

### 7.1 Terminal outcomes

| outcome              | meaning |
|----------------------|---------|
| `demo_scheduled`     | AI booked a Cal.com slot. `demo_booking_id` is set. |
| `not_interested`     | Lead declined and call ended politely. |
| `gatekeeper_only`    | Reached a non-decision-maker; `gatekeeper_contact` captured. |
| `callback_requested` | Lead asked to be called back; `preferred_callback_time` captured. |
| `voicemail`          | Reached voicemail; no message left. |
| `wrong_number`       | AI detected wrong person / bad number. |
| `completed`          | Call ended without a clearer disposition. |
| `failed`             | Carrier/technical failure; no useful conversation. |
| `disconnected`       | Media stream dropped mid-call. |
| `no_answer`          | Phone rang out (Twilio reported no answer). |

The legacy outcomes `transferred` and `in_progress` still exist but are
effectively unused by the attorney possibleos.

### 7.2 `possibleos calls list`

```
possibleos calls list [--limit=25] [--outcome=demo_scheduled]
```

Table columns: `call_id (short), lead, firm, state, outcome, duration_s, interest, demo_id, started`.

### 7.3 `possibleos calls show <call_id>`

Full JSON. Keys include everything on the `CallLog` model plus recording
metadata. Shape:

```json
{
  "call_id": "e5f6...",
  "patient_id": "LEAD-000001",
  "patient_name": "Jane Rothstein",
  "firm_name": "Rothstein & Associates",
  "state": "NY",
  "outcome": "demo_scheduled",
  "call_status": "called",
  "call_disposition": "demo_scheduled",
  "duration_seconds": 214,
  "started_at": "2026-04-12T14:03:22+00:00",
  "ended_at": "2026-04-12T14:06:56+00:00",
  "interest_level": 4,
  "is_decision_maker": true,
  "was_gatekeeper": false,
  "gatekeeper_contact": null,
  "pain_point_summary": "Medical-records retrieval burning 10 hrs/week of paralegal time.",
  "demo_booking_id": "bkg_abc123",
  "demo_scheduled_at": "2026-04-15T14:00:00-04:00",
  "demo_meeting_url": "https://cal.com/...",
  "followup_email_sent": false,
  "recording_path": "app/audio/recordings/2026/04/e5f6...mp3",
  "error_code": null,
  "error_message": null
}
```

### 7.4 `possibleos calls transcript <call_id>`

Prints the speaker-tagged transcript line-by-line:
```
ai: Hi, is this Jane? This is Alex Chen from Acme AI Labs …
patient: Yeah, what's this about?
ai: We build custom software and AI tools for personal injury firms …
```

### 7.5 `possibleos calls export --output file.csv [--outcome=demo_scheduled] [--limit=1000]`

CSV export with a CRM-friendly schema. Columns:
```
call_id, patient_id, patient_name, firm_name, lead_state, outcome,
call_status, call_disposition, interest_level, is_decision_maker,
was_gatekeeper, pain_point_summary, demo_booking_id, demo_scheduled_at,
demo_meeting_url, followup_email_sent, duration_seconds, started_at
```

Common post-export workflows:

```bash
# Demos booked this week
bin/possibleos calls export --outcome demo_scheduled --output this_week.csv

# All called-and-didn't-close for follow-up email
bin/possibleos calls export --outcome not_interested --output to_email.csv
```

---

## 8. `possibleos doctor` — interpreting results

Each row is a health check. All must be `✓` before a live call.

| check                   | meaning / fix |
|-------------------------|---------------|
| `env:OPENAI_API_KEY`    | Must be set, starts with `sk-`. Get from OpenAI dashboard. |
| `env:TWILIO_ACCOUNT_SID`| `AC…`. Twilio console. |
| `env:TWILIO_AUTH_TOKEN` | Paired with SID. Rotate regularly. |
| `env:TWILIO_FROM_NUMBER`| `+1…`. Must be outbound-enabled + SHAKEN/STIR registered. |
| `env:DATABASE_URL`      | `postgresql://user:pw@host:port/db`. |
| `db`                    | ✗ means DB unreachable or migration not run. `alembic upgrade head`. |
| `calcom`                | HTTP status from `GET /v2/me`. 2xx = key valid. 401 = bad key. |
| `openai`                | HTTP status from `GET /v1/models`. 2xx = key valid. 401 = bad. |
| `public_base_url`       | `PUBLIC_BASE_URL` must parse as an HTTP(S) URL with a host. Twilio fetches TwiML from this URL; if unset or a private IP, Twilio callbacks will silently fail and calls will time out with `media_stream_timeout`. |

Exit code `0` iff every check is `✓`.

---

## 9. Safety rails and dry-run

Three independent gates guard against unwanted live calls:

1. **`ALLOW_TWILIO_CALLS`** (env var): must be `"true"` or `place_twilio_call`
   raises `RuntimeError`. Set via `config init` or by editing `.env`.
2. **`allow_live_calls`** (DB `system_settings` row): additional boolean gate
   checked by the orchestrator. Default `false`. Toggle via the settings REST
   API (`POST /api/settings/allow-live-calls`).
3. **`allowed_phones`** (DB `system_settings` row, JSONB array): if populated
   and `allow_live_calls=true`, only these E.164 numbers can be dialed.

For testing, the sequence is:
```bash
# 1. add your cell to the allowlist via the running daemon:
curl -X POST http://127.0.0.1:8000/api/settings/allowed-phones \
     -H 'content-type: application/json' \
     -d '{"allowed_phones":["+15551234567"]}'
# 2. enable live calls in DB:
curl -X POST http://127.0.0.1:8000/api/settings/allow-live-calls \
     -H 'content-type: application/json' \
     -d '{"allowed":true}'
# 3. make sure env has ALLOW_TWILIO_CALLS=true
# 4. import yourself as a lead, then:
bin/possibleos call LEAD-000001
```

---

## 10. Typical AI-agent recipes

### Recipe: "import leads and start calling"
```bash
bin/possibleos doctor || { echo "fix doctor first"; exit 1; }
bin/possibleos leads import /tmp/leads_batch.csv
bin/possibleos dispatcher start
# monitor:
watch -n 10 'bin/possibleos dispatcher status | jq ".state, .recent_decisions[-3:]"'
```

### Recipe: "review last hour of calls"
```bash
bin/possibleos calls list --limit 50
# drill into one:
bin/possibleos calls show <call_id>
bin/possibleos calls transcript <call_id>
```

### Recipe: "daily pipeline snapshot"
```bash
bin/possibleos calls export --outcome demo_scheduled --output demos_booked.csv
bin/possibleos calls export --outcome callback_requested --output callback_queue.csv
bin/possibleos calls list --limit 200 | head -50
```

### Recipe: "daily warm list from Front"
Use this to refresh Precise Front person/firm warmth without sending outreach.
`front sync` is read-only against Front, persists cursors, and stops at the
hard API call budget.

```bash
bin/possibleos front sync --max-calls 300
bin/possibleos front status
bin/possibleos leads warm-list --limit 20
bin/possibleos front warm-batch --domains examplelaw.com,anotherfirm.com --name "Front warm review"
```

Review the named contacts before creating a lead-gen batch. `front warm-batch`
does not call Front and does not send email; it writes a normal recommended
lead-gen batch with pending items, `reason_json.basis = "front-warm"`, and a
link back to `/lead-gen?batch=<id>`.

### Recipe: "resync the firm mirror from the v2 contract"
Use this when EmailTag firm-intel has changed or before relying on local firm
resolution for lead-gen selection. The smoke sync caps the run and does not
restart any service.

```bash
bin/possibleos pif status
bin/possibleos pif sync --limit 20
bin/possibleos pif resolve smithlaw.com
bin/possibleos pif show smithlaw.com
```

Use `pif sync --full` only when the operator explicitly wants to ignore the
saved firm-intel watermark and recrawl every profile from EmailTag v2.

### Recipe: "research the warm list before a batch"
Use this when the warm list has matched PIF IDs but weak contact titles or
missing personas. PIF Stats research runs on production Precise infrastructure,
so trigger it manually and respect the POST budget.

```bash
bin/possibleos research status --tasks
bin/possibleos research warm --top 50 --kinds research,staff
bin/possibleos research sync
bin/possibleos personas map
bin/possibleos personas show examplelaw.com
bin/possibleos front warm-batch --domains examplelaw.com --name "Researched warm review"
```

`research warm` queues only safe PIF Stats task endpoints, skips completed
research, polls for completion up to the timeout, upserts titled
`firm_contacts`, stores behavior analysis on `front_firm_activity`, and maps
contact personas for the lead-email composer.

### Recipe: "the daily batch"
Use this for the deterministic daily lead-gen run. The loop is safe to leave
wired into the daemon because `daily_run_enabled` defaults to false and is
stored in DB settings, not env. Enabling it only creates approval-waiting
scheduled draft actions; approved sends still require operator approval.

```bash
bin/possibleos lead-gen daily-status
bin/possibleos lead-gen daily-run --dry-run
bin/possibleos lead-gen daily-run
bin/possibleos lead-gen daily-status
bin/possibleos actions list --status waiting_for_approval --type send_email

# Pin one composer variant for the whole run (every email, first-touch + follow-up):
bin/possibleos composer-ab variants                 # list valid keys + active state
bin/possibleos lead-gen daily-run --variant ai-audit

# Add more first-touch sends to today's existing daily run:
bin/possibleos lead-gen top-up --count 20 --variant ai-audit
```

To let the daemon create the morning batch during the 06:30-08:00 PT loop
window:

```bash
bin/possibleos lead-gen daily-enable
bin/possibleos lead-gen daily-status
bin/possibleos lead-gen daily-disable
```

The run checkpoints `gates`, `signals`, `research`, `personas`, `select`,
`batch`, `compose`, `schedule`, and `notify` in `lead_gen_daily_runs`. A
partial compose can be resumed by running the command again. The schedule stage
spreads drafted items across the policy send window, defaulting to 09:00-11:30
America/Los_Angeles, and leaves every action in `waiting_for_approval`.

### Recipe: "who competes with firm X"
Use this when a warm-list firm needs local PI competitor context. The rebuild
uses only local Mission Control cache tables and possibleos Postgres activity;
it does not call Front and does not call an LLM.

```bash
bin/possibleos front competitors rebuild
bin/possibleos front competitors summary
bin/possibleos front competitors show examplelaw.com --limit 10
```

The score combines local metro overlap, deterministic case-mix tags from cached
conversation text, lien/bill amount tier proximity, and shared Front activity.
Evidence dollar values are lien or bill amounts, not settlement values.

### Recipe: "explore a firm's competitive neighborhood"
Use this when an operator or agent needs the graph behind the browser
visualization. Search works across all firms with competitive features, not
just `/front` warm-list rows.

```bash
bin/possibleos front competitors search wilshire
bin/possibleos front competitors graph wilshirelawfirm.com --depth 1
bin/possibleos front competitors graph wilshirelawfirm.com --depth 2 --json
```

Depth 1 returns the center firm, direct neighbors, and all edges among that
node set. Depth 2 expands outward and caps the graph at 60 highest-score nodes.

### Recipe: "something's wrong — triage"
```bash
bin/possibleos status               # is daemon alive? any active call?
bin/possibleos doctor               # all green?
bin/possibleos dispatcher status    # state + recent_decisions tell you why it's not calling
tmux capture-pane -t possibleos -p | tail -100   # daemon logs
```

### Recipe: "take over a live call"
The AI has warmed up a gatekeeper or DM and you want to close the demo yourself.
Works from any frontend page via the `ActiveCallOverlay`:
```text
1. Click Listen (start streaming call audio to browser)
2. Put on headphones (avoids echo — mic will feed the call)
3. Click "Take over" — AI is muted server-side, your browser mic pipes in
4. Speak. Click "Hand back" when done; AI resumes on prospect's next turn.
```
Or from the CLI for scripting:
```bash
bin/possibleos calls takeover <call_id>         # server-side flag only
bin/possibleos calls takeover <call_id> --off   # release back to AI
```
CLI alone doesn't capture your voice — the UI owns the mic. The CLI is for
scripted mute (e.g., pause AI while an internal tool hands DTMF via Twilio REST).

### Recipe: "verify email pipeline before relying on follow-ups"
```bash
bin/possibleos email status                            # transport + gates
bin/possibleos email test --to you@example.com         # plain end-to-end ping
bin/possibleos email test --to you@example.com \
    --from "Pranav Modi <pranav@possiblemindshq.com>"
# preview the actual templates against a real address:
bin/possibleos email send-onepager --to you@example.com --name "Jane" --firm "Test Firm"
bin/possibleos email send-vm-followup --to you@example.com --first-name Jane
bin/possibleos email send-consult --to you@example.com --name "Jane Doe" \
    --slot "Wed Apr 30 at 2:00 PM PT" --firm "Test Firm"
```
If `email status` shows "NOT CONFIGURED", set `RESEND_API_KEY` (preferred) or
the `SMTP_*` block in `.env` and restart the daemon.
Sender selection defaults to `SMTP_FROM_EMAIL`, then `SMTP_USERNAME`, then
`RESEND_FALLBACK_FROM`. The `--from` test override must match one of those
configured addresses, or an address listed in `EMAIL_ALLOWED_FROM_ADDRESSES`.
Threaded lead-reply sends can use `THREAD_REPLY_FROM_EMAIL` to differ from the
generic notification sender.

### Recipe: "schedule a morning send window"
Use this when the operator has approved exact lead-gen drafts but wants them to
go out at specific Pacific morning times.

```bash
bin/possibleos actions send-email \
  --mode lead_gen \
  --to contact@example.com \
  --subject "Quick question" \
  --body "$(cat /tmp/approved-body.txt)" \
  --contact <contact_id> \
  --item <batch_item_id> \
  --at "09:30 PT"

bin/possibleos actions list --scheduled
bin/possibleos actions scheduler-status
```

`--at` accepts ISO-8601 with an offset, such as
`2026-06-11T09:30:00-07:00`, or `HH:MM PT|PDT|PST` for today in
America/Los_Angeles. If the PT time is already past today, the CLI exits
non-zero instead of rolling it to tomorrow. The daemon checks every 30 seconds,
executes only actions still `approved`, re-runs the normal policy gate at send
time, and marks actions more than 24 hours stale as `expired` instead of
sending them.

### Recipe: "edit and reschedule a queued draft"
Use this when a lead-gen batch item already has an `agent_draft` and the
operator wants to revise the exact copy before it goes out.

```bash
# Opens $EDITOR (fallback: vi) with:
# Subject: ...
#
# body...
bin/possibleos lead-gen edit-draft <batch_item_id> --at "10:30 PT"

bin/possibleos actions show <action_id>
bin/possibleos lead-gen show <batch_id>
```

If `reason_json.send_email_action_id` points to a live approved scheduled
action, `lead-gen edit-draft` updates that action's subject/body and optional
`scheduled_for` instead of creating a second queued send. If no live scheduled
action exists, it creates a new approved `send_approved_lead_gen_draft` action.
`--no-editor` reuses the current draft text; `--execute` is explicit and only
applies when creating a new unscheduled action. The command syncs
`reason_json.agent_draft` and `approval_status=approved` so the Lead Gen UI
matches the action queue.

To operate directly on an action:

```bash
bin/possibleos actions reschedule <action_id> --at "11:00 PT"
bin/possibleos actions cancel <action_id> --reason "operator changed plan"
```

### Recipe: "read the week's feedback"
Use this for the weekly lead-gen learning KPI. It reads the automatic
observation loop: sends, send failures, matched replies, tracked clicks,
consult bookings, finalized call dispositions, cancellations, and reschedules.

```bash
bin/possibleos lead-gen observations summary --since 7d
bin/possibleos lead-gen observations --since 7d
bin/possibleos lead-gen observations --since 7d --type email_reply_received
```

### Recipe: "check AI Audit attribution"
Use this when checking the AI-readiness freeware funnel from lead-gen email.

```bash
bin/possibleos aiaudit link --contact <contact_id>
bin/possibleos aiaudit clicks --since 7d
bin/possibleos lead-gen observations --since 7d --type link_clicked
```

The public redirect is `/aiaudit/go?t=<signed-token>`. It logs
`audit_link_clicks`, records a deterministic `link_clicked` observation with
`raw_event_json.channel = "ai_audit"`, and redirects to `AIAUDIT_PUBLIC_URL`
with non-PHI prefill plus `c=<click_id>`.

### Recipe: "check AI Visibility report attribution"
Use this when checking AI Search Visibility report links from lead-gen email.

```bash
bin/possibleos visibility-clicks --days 7
bin/possibleos lead-gen observations --since 7d --type link_clicked
```

The public redirect is `/v/<code>`. It logs `audit_link_clicks` with
`source = "visibility_report_email"`, records a `link_clicked` observation with
`raw_event_json.channel = "ai_visibility"`, and redirects to
`AIVIS_REPORT_BASE_URL/r/<scan_id>` with `c=<click_id>` and
`src=visibility_report_email`.

### Recipe: "morning mindset check"
```bash
bin/possibleos listening brief
bin/possibleos listening search "medical records follow up" --limit 8
bin/possibleos listening sources
```
Use this before approving outreach for the day. The brief is read from Mission
Control on `:8001`; if Mission Control is down the CLI exits non-zero and does
not alter possibleos state.

### Recipe: "pre-call prep"
```bash
bin/possibleos listening prep "Smith Injury Law"
bin/possibleos listening quotes --cluster medical-records-workflow --limit 5
```
`listening prep` looks up the firm/contact in local `patients` and
`firm_contacts`, fetches top matched listening insights, then makes one gateway
call to render persona, expected objections, and vocabulary. It is read-only.

### Recipe: "review every outbound touch with one firm"
```bash
bin/possibleos comms list --firm <pif_id> --since 30d --raw | jq '.items[] | {when:.occurred_at, ch:.channel, who:.contact_name, sum:.summary}'
```
Or open `https://<host>/firms/<pif_id>` and scroll to the **Communications** panel — same data, same shape, just rendered with channel pills + expandable rows.

### Recipe: "what went out today across all firms"
```bash
bin/possibleos comms list --since 24h
# narrow to one channel:
bin/possibleos comms list --since 24h --channel email
# or browse: open `/comms` in the UI and use the channel + range filters.
```

### Recipe: "stop all calling now"
```bash
bin/possibleos dispatcher stop       # pauses dispatching; in-flight call finishes
# to force-end an active call:
curl -X DELETE http://127.0.0.1:8000/api/calls    # drops the active_call marker
# or nuke the daemon:
tmux kill-session -t possibleos
```

---

### Recipe: "send blog-post outreach to a few firms"
LLM composes a personalized email per recipient; you preview each one and send
manually. No templates — voice is decided by the composer based on post + persona.
```bash
# 1. create the campaign (freezes post snapshot)
bin/possibleos outreach campaigns create --post-slug=musk-algorithm-ai-pi-firm

# 2. add audience — expand firm IDs into all emailable contacts
bin/possibleos outreach audience add --campaign=1 \
    --pif-ids=03382ee5-...,abcdef01-... --exclude-recent-days=14

# 3. batch-compose so previews don't block on the LLM
bin/possibleos outreach compose-all --campaign=1

# 4. step through one at a time — preview, then send or skip
bin/possibleos outreach next --campaign=1
bin/possibleos outreach preview --send=42 --html-out=/tmp/preview.html
bin/possibleos outreach send --send=42
# or:
bin/possibleos outreach skip --send=42 --reason="contact is on a competitor's payroll"

# 5. report
bin/possibleos outreach stats --campaign=1
bin/possibleos outreach events --campaign=1   # opens + clicks
```
Real Resend calls — every `send` is confirm-gated unless you pass `--yes`.
For tracking links (`/t/o/<token>.gif` opens, `/t/c/<token>` clicks) to reach
the daemon from a recipient's email client, set `OUTREACH_PUBLIC_BASE_URL`
to a public hostname before composing.

AI Visibility report emails also require `AIVIS_REPORT_BASE_URL` for the report
destination. Set `VISIBILITY_LINK_BASE_URL` only when `/v/<code>` short links
should use a different public hostname than `OUTREACH_PUBLIC_BASE_URL`.

---

## 11. REST API (used by the CLI — agents can call directly)

Base URL: `http://127.0.0.1:${BACKEND_PORT:-8000}` (or `PUBLIC_BASE_URL` externally).

The in-browser force-directed competitor graph on `/front` is UI-only. The
same graph data is fully available to agents and scripts through
`bin/possibleos front competitors graph --json` and
`GET /api/front/competitors/graph`.

Relevant endpoints:

| method | path | notes |
|--------|------|-------|
| GET  | `/api/status` | overall state (queue, dispatcher, active call) |
| POST | `/api/call/start` | body `{"patient_id": "...", "mode": "twilio"}` |
| GET  | `/api/dispatcher/status` | |
| POST | `/api/dispatcher/toggle` | body `{"enabled": true\|false}` |
| GET  | `/api/dispatcher/decisions` | full decision log |
| GET  | `/api/calls?limit=25&offset=0` | |
| GET  | `/api/calls/{call_id}` | |
| GET  | `/api/calls/active` | |
| GET  | `/api/communications?channel=&since=&until=&q=&status=&limit=` | cross-firm outbound feed (calls + voicemail + sms + email) |
| GET  | `/api/firms/{pif_id}/communications?channel=&since=&limit=` | per-firm outbound timeline |
| POST | `/api/calls/{call_id}/takeover` | body `{"enabled": bool}` — mute AI / resume |
| GET  | `/api/statistics/today` | |
| POST | `/api/settings/allow-live-calls` | body `{"allowed": true}` |
| POST | `/api/settings/allowed-phones` | body `{"allowed_phones": ["+1..."]}` |
| POST | `/api/twilio/twiml/{stream_id}` | Twilio webhook — do **not** call manually |
| POST | `/api/twilio/status` | Twilio status callback |
| POST | `/api/twilio/recording-status/{call_id}` | Twilio recording callback |
| POST | `/api/resend/webhook` | Resend delivery/engagement webhook. Public ingress, no CLI wrapper; verifies Svix headers when `RESEND_WEBHOOK_SECRET` is set. |
| GET  | `/api/inbound-email/config` | masked Zoho IMAP reader config |
| POST | `/api/inbound-email/poll` | poll Zoho IMAP, store inbound replies, match lead-gen items, optionally classify |
| GET  | `/api/inbound-email?matched=&limit=` | list stored inbound messages |
| GET  | `/api/operator-notifications/pending` | pending persisted operator action-center notifications |
| POST | `/api/operator-notifications/{id}/acknowledge` | dismiss a notification so it does not pop again |
| POST | `/api/operator-notifications/{id}/send-draft` | send the notification draft as a threaded Resend/SMTP reply and dismiss/action the notification |
| GET  | `/api/outreach/campaigns` | list outreach campaigns (`?status=`) |
| POST | `/api/outreach/campaigns` | create campaign (body: `post_slug`, optional sender/intent/notes) |
| GET  | `/api/outreach/campaigns/{id}` | full campaign detail + stats |
| GET  | `/api/outreach/campaigns/{id}/stats` | per-status + open/click counts |
| POST | `/api/outreach/campaigns/{id}/audience` | body: `contact_ids[]` or `pif_ids[]` |
| GET  | `/api/outreach/campaigns/{id}/sends` | list recipients (`?status=`) |
| GET  | `/api/outreach/campaigns/{id}/next` | next composed/pending recipient (step-through UI) |
| GET  | `/api/outreach/sends/{id}` | single recipient row |
| POST | `/api/outreach/sends/{id}/compose` | LLM-compose; body `{regenerate, model}` |
| GET  | `/api/outreach/sends/{id}/preview` | exact subject/HTML/plaintext that will be sent |
| POST | `/api/outreach/sends/{id}/send` | fire the email via Resend (real side effect) |
| POST | `/api/outreach/sends/{id}/skip` | body `{reason}` |
| POST | `/api/outreach/sends/{id}/edit` | body `{subject?, body_html?, plaintext?, by?}` |
| GET  | `/api/outreach/blog-posts` | known blog post slugs (for the UI builder) |
| GET  | `/t/o/{token}.gif` | **public** — 1x1 pixel, logs open. No auth. |
| GET  | `/t/c/{token}` | **public** — 302 to post URL, logs click. No auth. |

An agent that doesn't want to shell out can drive the system entirely via
these JSON endpoints. The CLI commands are thin wrappers around them, with
the single addition of the bulk `leads import` / `calls export` paths which
hit the DB directly.

---

## 12. Read-only filesystem inspection

Possible OS exposes a narrow read-only filesystem surface for the master agent
and operators. It is not arbitrary shell. It only reads inside the repo root,
blocks traversal and sensitive files, and records product traces.

```bash
bin/possibleos fs list app/services --json
bin/possibleos fs read app/services/master_agent.py --start 1200 --end 1220 --json
bin/possibleos fs search _build_wake_context app/services --json
bin/possibleos fs git-status --json
bin/possibleos fs git-diff --path app/services/master_agent.py --json
bin/possibleos fs git-log --limit 10 --json
bin/possibleos fs git-show HEAD --path app/services/master_agent.py --json
```

Use this for codebase inspection, debugging context, and system understanding.
Do not replace it with raw shell in the heartbeat runner.

---

## 13. Common failure modes and fixes

| symptom | likely cause | fix |
|---------|--------------|-----|
| `call` returns HTTP 409 | another call in progress | `curl -X DELETE /api/calls` to clear, or wait |
| dispatcher stays in `no_candidate` | all leads cooling down, or no leads match state window | `leads list` to inspect; adjust `per_state_hours` or wait |
| every call ends `failed` with `error_code=media_stream_timeout` | `PUBLIC_BASE_URL` is wrong or not reachable by Twilio | fix ngrok / DNS / firewall |
| every call ends `failed` with `error_code=openai_connect_failed` | `OPENAI_API_KEY` invalid, quota exhausted, or no Realtime access | verify in OpenAI console; `doctor` |
| `book_demo` always fails | Cal.com key or event type id wrong | `curl -H "Authorization: Bearer $CALCOM_API_KEY" https://api.cal.com/v2/me`; verify `event_type_id` in DB `system_settings.calcom_config` |
| dispatcher runs but never picks up a lead | all candidates outside state window; or `system_enabled=false` | `dispatcher status` + `settings`; check `per_state_hours` in DB |
| CLI can't talk to daemon (connection refused) | daemon not running, wrong port, or firewall | `possibleos serve` in one terminal; confirm `BACKEND_PORT` matches |

---

## 14. Data model cheat sheet (for agents composing queries)

Tables (Postgres, via SQLAlchemy):

- `patients` — leads. Primary key `patient_id`. Attorney columns:
  `name, phone, firm_name, state, practice_area, website, email, title,
  source, tags (jsonb), notes`. Retry: `attempt_count, last_attempt_at,
  last_outcome, due_by, priority_bucket`.
- `call_logs` — one row per call. Primary key `call_id`. Post-call capture:
  `pain_point_summary, interest_level (1-5), is_decision_maker,
  was_gatekeeper, gatekeeper_contact (jsonb), demo_booking_id,
  demo_scheduled_at, demo_meeting_url, followup_email_sent`.
- `system_settings` — singleton (`id=1`). JSONB columns:
  `business_hours, dispatcher_settings, daily_report, calcom_config,
  sales_context, per_state_hours`. Plus `allow_live_calls, allowed_phones`.
- `dispatcher_events` — every dispatcher decision, indexed by timestamp.

Agents querying the DB directly: always read via the provider classes
(`app.providers.*`) when possible to pick up the schema conversions. Direct
SQL is fine for read-only reporting.

---

## 15. The AI's system prompt (what the caller actually says)

Rendered from `app/prompts/attorney_cold_call.py::render_system_prompt`.
The slots are filled at call time from the lead + `system_settings.sales_context`:

- `{rep_name}` — spoken as "Hi, this is {rep_name}".
- `{rep_company}` — "… from {rep_company}".
- `{lead_name}`, `{lead_first_name}`, `{title_clause}`, `{firm_name_clause}`, `{state_clause}`.
- `{product_context}` — free-form paragraph the operator supplies via
  `sales_context.product_context` or `PRODUCT_CONTEXT` env var.

**If you want to change the pitch** (e.g. emphasise a new product line), edit
`PRODUCT_CONTEXT` in `.env` OR update `system_settings.sales_context.product_context`
via the settings API. No code change needed.

**Available tools the AI can call during a conversation:**
1. `check_availability(days_ahead=7)` → returns up to 5 slots.
2. `book_demo(slot_iso, invitee_email, pain_point_summary)` → books on Cal.com.
3. `mark_gatekeeper(best_contact_name?, best_contact_email?, best_contact_phone?, notes?)`.
4. `send_followup_email(invitee_email, message_type, custom_note?)`.
5. `end_call(outcome, pain_point_summary?, interest_level?, is_decision_maker?, callback_requested_at?)`.

All five are implemented in `call_orchestrator.py::_autocaller_*` and
`_handle_function_call`.

---

## 16. Commit hygiene

This codebase is on branch `feature/attorney-autocaller`. Don't push to `main`
until you've done at least one successful live demo-booking call end-to-end
(`doctor` green + one `outcome=demo_scheduled` in `calls list`).

When asking the user to commit, describe the change concretely ("added X
command"; don't say "updated CLI").
