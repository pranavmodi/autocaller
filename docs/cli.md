# Autocaller CLI — Operator's Guide (for humans and AI agents)

This document is the canonical reference for driving the autocaller from the
command line. It is written to be consumed by an AI agent as well as a human
operator: commands, argument schemas, return shapes, failure modes, and
recovery steps are spelled out explicitly.

**Project root:** `/home/pranav/OutboundVoiceAI`
**Entry points (equivalent):**
- `bin/autocaller <command>` — shell wrapper, loads `.env`, prefers `.venv`
- `.venv/bin/python -m app.cli <command>` — direct invocation

All examples below use `bin/autocaller` (referred to as `autocaller` for short).

---

## 1. System architecture in one paragraph

The autocaller has two processes: the **daemon** (FastAPI, long-running) and
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
cd /home/pranav/OutboundVoiceAI
.venv/bin/pip install -r requirements.txt
```

### 2.3 Configure `.env`
```bash
bin/autocaller config init
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
bin/autocaller doctor
```
Every row must be `✓` before attempting a live call. See §8 for interpreting
each row.

---

## 3. Top-level command reference

```
autocaller <command> [options]

Commands
  serve          Start the FastAPI daemon (foreground).
  call           Place a call immediately (bypass dispatcher).
  status         One-shot system status summary (dispatcher + current call).
  doctor         Validate env + connectivity (db, Twilio, OpenAI, Cal.com).
  leads          Manage leads (import, list, show, add, remove, sync-mission).
  calls          Inspect call history + transcripts + judge.
  dispatcher     Control the auto-dispatcher (start, stop, batch, status, clear-active).
  config         Config / .env wizard + inspection.
  system         Global on/off — master kill switch.
  mock           Mock-mode toggle (redirect all Twilio calls to a mock phone).
  allowlist      Manage allowed_phones (phone allowlist).
  followups      GTM follow-up queue — calls awaiting action.
  listening      Mission Control mindset brief, insights, sources, and prep.
```

Every command accepts `--help`. Exit code is `0` on success, `1` on any error
(network, validation, missing resource).

### New-command reference (v1.1)

| command | purpose |
|---|---|
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
| `contacts backfill [--limit=N]` | Pull leadership rosters from PIF Stats + autocaller patient DM rows into `firm_contacts`. Idempotent. Run once before using `sequences start`. |
| `contacts list [--firm=<pif_id>] [--limit=N]` | List firm_contacts rows. Without `--firm`, walks across firms. |
| `sequences preview <contact_id>` | Render the four (or three, if no Yelp quote) email drafts for one contact against their actual personalization data. Read-only. |
| `sequences start <contact_id>` | Start the 4-step sequence for one contact. Idempotent — second start returns 409 with current state. Sends gated by `ALLOW_SEQUENCE_SEND=true`. |
| `sequences list [--status=active\|paused\|completed]` | List sequence rows + which step each is on. |
| `inbound status` | Show whether Zoho IMAP inbox reading is configured. Sensitive values masked. |
| `inbound poll [--limit=N --classify --mark-seen]` | Poll Zoho IMAP for unread/recent replies, store inbound rows, match lead-gen contacts, and create observations. |
| `inbound list [--matched=yes\|no]` | List stored inbound email messages. |
| `todos list [--area=lead-gen] [--status=not_started] [--json]` | Show the DB-backed editable project backlog. |
| `todos add <title> [--area=lead-gen --status=not_started --body=... --source-url=...]` | Add a DB-backed todo. |
| `todos update <id> [--title=... --status=done --body=... --clear-source-url]` | Edit a DB-backed todo. |
| `todos delete <id>` | Delete a DB-backed todo. |
| `lead-gen email-agent-slice [--limit=3 --composer-variant=... --approval-ready --batch=<batch_id> --json]` | Select senior decision-maker contacts, collect bounded internal evidence, compose approval-ready drafts with the Possible Minds email composer skill, and create no-send durable `send_email mode=lead_gen` actions. With `--batch`, skip selection and compose for an existing batch's pending undrafted items (operator- or agent-curated lists, e.g. Front-warm shortlists). |
| `actions list [--status=approved --type=send_approved_lead_gen_draft --json]` | List durable Possible OS action execution records. |
| `actions show <action_id> [--json]` | Show one action with its append-only event timeline. |
| `actions policy-check <action_id> [--actor=operator --json]` | Run the reusable policy checker without executing the action. |
| `actions execute <action_id> [--actor=operator --json]` | Execute one policy-approved action through its narrow executor. |
| `actions execute-approved-lead-gen [--limit=1 --actor=operator --json]` | Execute already-approved `send_email mode=lead_gen` actions through the durable policy gate. This is the narrow action the master agent may use when approved-send automation is enabled. Successful sends link the action result to the `email_logs` row, transport, message id, and log status. |
| `actions send-approved-lead-gen-draft --item=<batch_item_id> --subject=... --body=... [--approved-by=operator] [--no-execute]` | Create and optionally execute the first high-risk action slice: an exact approved lead-gen email draft sent through the existing Zoho-backed lead-gen path. |
| `actions send-email --mode=test --to=<email> --subject=... --body=... [--approved-by=operator --from=... --no-execute --json]` | Create, policy-check, and optionally execute a regular durable test email action. |
| `actions send-email --mode=lead_gen --to=<email> --subject=... --body=... --contact=<contact_id> --item=<batch_item_id> [--pif=<pif_id> --firm=... --approved-by=operator --no-execute --json]` | Create, policy-check, and optionally execute an exact approved lead-gen email action. Policy verifies recipient/contact match, approval hashes, consult link, Zoho transport, no suppression, and no prior successful send for the same item/recipient. |
| `actions send-test-email --to=<email> [--subject=... --body=... --approved-by=operator --from=... --no-execute --json]` | Convenience alias for `actions send-email --mode=test`. Use the regular email action family for master-agent execution-path tests instead of free-form email shell commands. |
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
bin/autocaller lead-gen email-agent-slice --limit 3 --approval-ready
```

That command creates a normal lead-gen batch, stores research evidence and an
`agent_draft` on each selected batch item, and creates durable
`send_email mode=lead_gen` actions in `waiting_for_approval`. It does not send
email. For no-send policy validation of an exact approved action, run:

```bash
bin/autocaller lead-gen email-agent-slice --limit 3 --approve-actions --policy-check-first-action --json
```

---

## 4. Daemon lifecycle

### `autocaller serve`
Starts the FastAPI daemon in the foreground on `BACKEND_PORT` (default 8000).
Runs the dispatcher, mounts the Twilio webhooks at `/api/twilio/*`, and exposes
the REST API.

```bash
bin/autocaller serve                 # foreground, production log level
bin/autocaller serve --reload        # auto-reload on code change (dev only)
bin/autocaller serve --port 9000     # bind on a different port
```

**For AI agents / unattended operation:** Run the daemon under a supervisor
(systemd, tmux, or `nohup`). The CLI calls below assume the daemon is reachable
at `http://127.0.0.1:${BACKEND_PORT:-8000}`.

Example `tmux` pattern:
```bash
tmux new -d -s autocaller 'cd /home/pranav/OutboundVoiceAI && bin/autocaller serve'
tmux capture-pane -t autocaller -p | tail -20   # peek at logs
```

### Stopping the daemon
```bash
tmux kill-session -t autocaller
# or: pkill -f 'uvicorn app.main:app'
```

Shutdown is clean — the dispatcher stops, any in-flight call is ended with
outcome `FAILED` (the caller on the other end will hear a hangup).

---

## 5. Lead management

### 5.1 CSV import (`autocaller leads import`)

```
autocaller leads import <csv_path> [--source=csv] [--dry-run]
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

### 5.2 List (`autocaller leads list`)
```
autocaller leads list [--state=CA] [--limit=50]
```
Table columns: `id, name, firm, state, phone, title, attempts, last_outcome`.
Sorted by `priority_bucket` then `updated_at desc`.

### 5.3 Show (`autocaller leads show <lead_id>`)
Prints the full row as JSON (pretty-printed by Rich). Exit code `1` if not
found — agents should check the exit status, not parse the error string.

### 5.4 Add / remove
```
autocaller leads add --name "Jane Doe" --phone 555... [--firm ...] [--state CA] [--email ...] [--title Partner] [--practice-area "personal injury"]
autocaller leads remove <lead_id>
```

---

## 6. Placing calls

There are two ways a call goes out: **manually** (single-shot) or **dispatched**
(auto polling loop).

### 6.1 Manual single-shot (`autocaller call`)

```
autocaller call <lead_id> [--mode=twilio|web]
```

- `--mode=twilio` (default): real PSTN call via Twilio. **Requires** `ALLOW_TWILIO_CALLS=true` **and** the lead's phone in `allowed_phones` (until you remove the allowlist).
- `--mode=web`: browser-voice mode. Needs a connected voice WS client. In a headless deployment this is effectively unused — retained for dev testing.

The daemon must be running. Returns the created `call` object as JSON (shape described in §7.2).

**Failure responses:**
| exit | cause | fix |
|------|-------|-----|
| 1    | HTTP 400 `patient_id is required` | pass a valid lead id |
| 1    | HTTP 409 `Call could not be started` | another call in progress, OR `ALLOW_TWILIO_CALLS` gate, OR lead not in `allowed_phones`. Check `autocaller status` and daemon logs. |
| 1    | network error | daemon not running — `autocaller serve` |

### 6.2 Auto-dispatched (`autocaller dispatcher …`)

```
autocaller dispatcher start    # enable polling (kicks off first call if eligible)
autocaller dispatcher stop     # pause — in-flight call continues until natural end
autocaller dispatcher status   # JSON: state, last decision, running flag, config
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
autocaller dispatcher status | jq .recent_decisions
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
effectively unused by the attorney autocaller.

### 7.2 `autocaller calls list`

```
autocaller calls list [--limit=25] [--outcome=demo_scheduled]
```

Table columns: `call_id (short), lead, firm, state, outcome, duration_s, interest, demo_id, started`.

### 7.3 `autocaller calls show <call_id>`

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

### 7.4 `autocaller calls transcript <call_id>`

Prints the speaker-tagged transcript line-by-line:
```
ai: Hi, is this Jane? This is Alex Chen from Acme AI Labs …
patient: Yeah, what's this about?
ai: We build custom software and AI tools for personal injury firms …
```

### 7.5 `autocaller calls export --output file.csv [--outcome=demo_scheduled] [--limit=1000]`

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
bin/autocaller calls export --outcome demo_scheduled --output this_week.csv

# All called-and-didn't-close for follow-up email
bin/autocaller calls export --outcome not_interested --output to_email.csv
```

---

## 8. `autocaller doctor` — interpreting results

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
bin/autocaller call LEAD-000001
```

---

## 10. Typical AI-agent recipes

### Recipe: "import leads and start calling"
```bash
bin/autocaller doctor || { echo "fix doctor first"; exit 1; }
bin/autocaller leads import /tmp/leads_batch.csv
bin/autocaller dispatcher start
# monitor:
watch -n 10 'bin/autocaller dispatcher status | jq ".state, .recent_decisions[-3:]"'
```

### Recipe: "review last hour of calls"
```bash
bin/autocaller calls list --limit 50
# drill into one:
bin/autocaller calls show <call_id>
bin/autocaller calls transcript <call_id>
```

### Recipe: "daily pipeline snapshot"
```bash
bin/autocaller calls export --outcome demo_scheduled --output demos_booked.csv
bin/autocaller calls export --outcome callback_requested --output callback_queue.csv
bin/autocaller calls list --limit 200 | head -50
```

### Recipe: "something's wrong — triage"
```bash
bin/autocaller status               # is daemon alive? any active call?
bin/autocaller doctor               # all green?
bin/autocaller dispatcher status    # state + recent_decisions tell you why it's not calling
tmux capture-pane -t autocaller -p | tail -100   # daemon logs
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
bin/autocaller calls takeover <call_id>         # server-side flag only
bin/autocaller calls takeover <call_id> --off   # release back to AI
```
CLI alone doesn't capture your voice — the UI owns the mic. The CLI is for
scripted mute (e.g., pause AI while an internal tool hands DTMF via Twilio REST).

### Recipe: "verify email pipeline before relying on follow-ups"
```bash
bin/autocaller email status                            # transport + gates
bin/autocaller email test --to you@example.com         # plain end-to-end ping
bin/autocaller email test --to you@example.com \
    --from "Pranav Modi <pranav@possiblemindshq.com>"
# preview the actual templates against a real address:
bin/autocaller email send-onepager --to you@example.com --name "Jane" --firm "Test Firm"
bin/autocaller email send-vm-followup --to you@example.com --first-name Jane
bin/autocaller email send-consult --to you@example.com --name "Jane Doe" \
    --slot "Wed Apr 30 at 2:00 PM PT" --firm "Test Firm"
```
If `email status` shows "NOT CONFIGURED", set `RESEND_API_KEY` (preferred) or
the `SMTP_*` block in `.env` and restart the daemon.
Sender selection defaults to `SMTP_FROM_EMAIL`, then `SMTP_USERNAME`, then
`RESEND_FALLBACK_FROM`. The `--from` test override must match one of those
configured addresses, or an address listed in `EMAIL_ALLOWED_FROM_ADDRESSES`.
Threaded lead-reply sends can use `THREAD_REPLY_FROM_EMAIL` to differ from the
generic notification sender.

### Recipe: "morning mindset check"
```bash
bin/autocaller listening brief
bin/autocaller listening search "medical records follow up" --limit 8
bin/autocaller listening sources
```
Use this before approving outreach for the day. The brief is read from Mission
Control on `:8001`; if Mission Control is down the CLI exits non-zero and does
not alter autocaller state.

### Recipe: "pre-call prep"
```bash
bin/autocaller listening prep "Smith Injury Law"
bin/autocaller listening quotes --cluster medical-records-workflow --limit 5
```
`listening prep` looks up the firm/contact in local `patients` and
`firm_contacts`, fetches top matched listening insights, then makes one gateway
call to render persona, expected objections, and vocabulary. It is read-only.

### Recipe: "review every outbound touch with one firm"
```bash
bin/autocaller comms list --firm <pif_id> --since 30d --raw | jq '.items[] | {when:.occurred_at, ch:.channel, who:.contact_name, sum:.summary}'
```
Or open `https://<host>/firms/<pif_id>` and scroll to the **Communications** panel — same data, same shape, just rendered with channel pills + expandable rows.

### Recipe: "what went out today across all firms"
```bash
bin/autocaller comms list --since 24h
# narrow to one channel:
bin/autocaller comms list --since 24h --channel email
# or browse: open `/comms` in the UI and use the channel + range filters.
```

### Recipe: "stop all calling now"
```bash
bin/autocaller dispatcher stop       # pauses dispatching; in-flight call finishes
# to force-end an active call:
curl -X DELETE http://127.0.0.1:8000/api/calls    # drops the active_call marker
# or nuke the daemon:
tmux kill-session -t autocaller
```

---

### Recipe: "send blog-post outreach to a few firms"
LLM composes a personalized email per recipient; you preview each one and send
manually. No templates — voice is decided by the composer based on post + persona.
```bash
# 1. create the campaign (freezes post snapshot)
bin/autocaller outreach campaigns create --post-slug=musk-algorithm-ai-pi-firm

# 2. add audience — expand firm IDs into all emailable contacts
bin/autocaller outreach audience add --campaign=1 \
    --pif-ids=03382ee5-...,abcdef01-... --exclude-recent-days=14

# 3. batch-compose so previews don't block on the LLM
bin/autocaller outreach compose-all --campaign=1

# 4. step through one at a time — preview, then send or skip
bin/autocaller outreach next --campaign=1
bin/autocaller outreach preview --send=42 --html-out=/tmp/preview.html
bin/autocaller outreach send --send=42
# or:
bin/autocaller outreach skip --send=42 --reason="contact is on a competitor's payroll"

# 5. report
bin/autocaller outreach stats --campaign=1
bin/autocaller outreach events --campaign=1   # opens + clicks
```
Real Resend calls — every `send` is confirm-gated unless you pass `--yes`.
For tracking links (`/t/o/<token>.gif` opens, `/t/c/<token>` clicks) to reach
the daemon from a recipient's email client, set `OUTREACH_PUBLIC_BASE_URL`
to a public hostname before composing.

---

## 11. REST API (used by the CLI — agents can call directly)

Base URL: `http://127.0.0.1:${BACKEND_PORT:-8000}` (or `PUBLIC_BASE_URL` externally).

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
bin/autocaller fs list app/services --json
bin/autocaller fs read app/services/master_agent.py --start 1200 --end 1220 --json
bin/autocaller fs search _build_wake_context app/services --json
bin/autocaller fs git-status --json
bin/autocaller fs git-diff --path app/services/master_agent.py --json
bin/autocaller fs git-log --limit 10 --json
bin/autocaller fs git-show HEAD --path app/services/master_agent.py --json
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
| CLI can't talk to daemon (connection refused) | daemon not running, wrong port, or firewall | `autocaller serve` in one terminal; confirm `BACKEND_PORT` matches |

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
