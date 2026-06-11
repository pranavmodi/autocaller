---
name: autocaller
description: Operate the attorney cold-call autocaller — place Twilio calls driven by OpenAI Realtime, manage leads, inspect call transcripts, and book demos via Cal.com. Use when the user asks to place a call, import leads, diagnose a call, check why a lead wasn't called, review a transcript, or configure the caller. Project at /home/pranav/autocaller.
---

# Autocaller operator skill

A FastAPI daemon + Typer CLI that cold-calls US personal-injury attorneys, runs an AI discovery conversation, and books demos on Cal.com. This skill tells you how to drive it without shooting yourself in the foot.

Full reference: `docs/cli.md` (read it for anything not covered here).

Lead-generation work has a living concept document:
`docs/CYBERNETIC_LEAD_GEN_CONCEPT.md`. If you add or change a lead-gen feedback
source, learning step, policy lever, suppression rule, sequence behavior,
routing action, or implemented capability, update that document in the same
change set. Keep its `What Exists Today`, feedback sources, degrees of freedom,
and open gaps accurate.

Zoho Mail is the current inbound mailbox provider. Use `autocaller inbound
status`, `autocaller inbound poll`, and `autocaller inbound list` to read
inbound replies through IMAP. Credentials come from `ZOHO_IMAP_*` env vars; do
not print or store mailbox passwords.

Possible OS now has a master-agent heartbeat and durable subagent task board.
Use `bin/autocaller agents status`, `bin/autocaller agents heartbeat`,
`bin/autocaller agents config --interval-seconds=<seconds>`,
`bin/autocaller agents set-goal "..."`, `bin/autocaller agents list`, and
`bin/autocaller agents show <task_id>` to
inspect or configure it. The V1 heartbeat reads `soul.md` as protected
read-only constitutional context, records traces, checks active subagent tasks,
and marks stale workers. Its persisted period can be changed from the UI or CLI
without a backend restart. Human-friendly heartbeat status is composed through
the OpenClaw gateway using `app/skills/master-agent-status/SKILL.md` when
available; gateway failure falls back to deterministic status. The status call
also passes `soul.compact.md` as compact constitutional guidance before volatile
heartbeat state, while full `soul.md` remains protected metadata unless a deeper
strategic task explicitly needs it. It must not edit `soul.md`. When the task
has a manual goal set through `agents set-goal`, heartbeat respects that goal
until it expires instead of immediately synthesizing over it. When the task
board is idle, V1 may auto-delegate one safe queued SystemsHealthAgent task for
log observation and bug-fix delegation. SystemsHealthAgent now has a read-only
observe/report worker via `bin/autocaller agents run-systems-health`; it must
not edit code, restart services, send email, place calls, or modify external
state. Use `bin/autocaller agents capabilities` for the capability registry and
`bin/autocaller agents goals` for durable adaptive goals.
Use `bin/autocaller agents run-research-scout` to execute one queued
ResearchScoutAgent task and write a durable learning note/report.
Heartbeat can execute already-approved lead-gen email actions only when enabled
with `bin/autocaller agents config --auto-send-approved-lead-gen
--auto-send-limit=<N>`. This does not let the agent create or alter email
content; it only drains exact approved `send_email mode=lead_gen` actions
through the durable policy gate.

Possible OS also has a first durable action-execution slice. Use
`bin/autocaller actions list`, `actions show <id>`, `actions policy-check <id>`,
`actions scheduler-status`, `actions execute <id>`, `actions cancel <id>`, and
`actions reschedule <id> --at "10:30 PT"` to inspect, run, cancel, or move
policy-checked actions. `actions cancel` only works before execution while the
action is `waiting_for_approval` or `approved`; `actions reschedule` only works
for approved scheduled actions and prints old -> new in PT and UTC. The first
high-risk supported action is `send_approved_lead_gen_draft`, exposed as
`bin/autocaller actions send-approved-lead-gen-draft --item=<batch_item_id>
--subject=... --body=...`; it creates an exact approved draft action, checks
policy, and sends through the existing Zoho-backed lead-gen path. Regular
durable email actions use `bin/autocaller actions send-email --mode=test
--to=<email> --subject=... --body=...`; `actions send-test-email` is a
convenience alias. Lead-gen email actions use
`bin/autocaller actions send-email --mode=lead_gen --contact=<contact_id>
--item=<batch_item_id> --to=<email> --subject=... --body=... --no-execute`.
Both `actions send-approved-lead-gen-draft` and `actions send-email` accept
`--at "09:30 PT"` or an ISO-8601 time with offset. With `--at`, the CLI stores
`scheduled_for`, runs the normal policy check, prints PT and UTC, and does not
send immediately; the daemon's scheduled-action loop sends due approved actions
every 30 seconds and expires anything more than 24 hours stale.
Policy verifies the exact approval hashes, contact/recipient match, consult
link, Zoho transport, no selection suppressions, and no prior successful send
for the same item/recipient.
Use `bin/autocaller lead-gen edit-draft <batch_item_id>` to open the current
lead-gen draft in `$EDITOR` as `Subject: ...`, blank line, body. Add
`--at "10:30 PT"` to schedule/reschedule from the same save, or `--no-editor`
to reuse the current text. If the item already points at a live approved
scheduled action, edit-draft updates that action's subject/body and time in
place instead of creating a duplicate. Otherwise it creates a new approved
`send_approved_lead_gen_draft` action. It also syncs
`reason_json.agent_draft`, `send_email_action_id`, and
`approval_status=approved` so the Lead Gen UI matches the action queue.
`bin/autocaller actions execute-approved-lead-gen --limit=<N>
--actor=master-agent` executes only already-approved lead-gen email actions via
that same policy gate. This is the action heartbeat uses when approved-send
automation is enabled. Successful `send_email` executions write send evidence
onto the action's `execution_result`: recipient, subject, provider message id,
transport, linked `email_logs.id`, email log status, and timestamp. Heartbeat
recent-action summaries expose the same evidence so the master agent can see
what actually happened.

For the current master-agent lead-generation slice, use
`bin/autocaller lead-gen email-agent-slice --limit 3 --approval-ready`. To compose for a hand-curated batch instead of auto-selection: `lead-gen email-agent-slice --batch <batch_id> --limit 10`.
It selects senior decision-maker contacts from `firm_contacts`, collects
bounded internal evidence, composes drafts with
`app/skills/possible-minds-lead-email-composer/SKILL.md`, stores each
`agent_draft` on the lead-gen batch item, and creates no-send durable
`send_email mode=lead_gen` actions. Add `--approve-actions
--policy-check-first-action --json` only when you need a no-send policy-check
artifact for an exact approved draft. Do not send email from free-form shell
commands or LLM-generated recipient/body payloads.

---

## First: establish situational awareness

Before doing anything else, run:

```bash
cd /home/pranav/autocaller
bin/autocaller doctor                      # env + connectivity sanity check
curl -s http://127.0.0.1:8099/health       # daemon alive? (port is 8099 on this host)
ps aux | grep -v grep | grep 'app.cli.*serve' | head -1
curl -s http://127.0.0.1:8099/api/dispatcher/status | jq . 2>/dev/null || curl -s http://127.0.0.1:8099/api/dispatcher/status
```

**Defaults you must know:**
- **Backend port is `8099` (NOT 8000)** on this host — port 8000 is already taken by another service (`autointake`). `.env` has `BACKEND_PORT=8099`. Do not try to bind 8000.
- **Public URL uses a cloudflared quick tunnel** — ephemeral, regenerated on restart. Check `/tmp/cf.log` for the current URL and ensure `PUBLIC_BASE_URL` in `.env` matches.
- **Postgres**: `postgresql://autocaller:dev@localhost:5432/autocaller`, managed by native `systemctl postgresql` (no Docker).
- **Virtualenv**: `.venv/` at repo root. Use `.venv/bin/python` for any direct Python invocation.

---

## The four moving pieces

| piece | runs where | how to check |
|---|---|---|
| Postgres | `localhost:5432`, DB `autocaller` | `sudo -u postgres psql -d autocaller -c '\dt'` |
| FastAPI daemon | `0.0.0.0:8099` (via cloudflared → HTTPS) | `curl /health`, `ps aux \| grep app.cli` |
| cloudflared tunnel | backgrounded, logs to `/tmp/cf.log` | `grep trycloudflare.com /tmp/cf.log \| head -1` |
| External services | OpenAI Realtime, Twilio, Cal.com | `bin/autocaller doctor` |

All four must be healthy for a call to work end to end.

---

## Starting from scratch (cold boot)

```bash
# 1. Ensure Postgres is up
service postgresql status | grep Active

# 2. Start cloudflared tunnel to the daemon port
pkill -f 'cloudflared tunnel' 2>/dev/null
cloudflared tunnel --url http://127.0.0.1:8099 > /tmp/cf.log 2>&1 &
disown
# wait ~10s, then extract the URL:
PUBLIC_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf.log | head -1)
echo "$PUBLIC_URL"

# 3. Update .env with the current tunnel URL
sed -i "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=$PUBLIC_URL|" .env

# 4. Start daemon (foreground for real ops; use nohup + disown for background)
pkill -f 'app.cli.*serve' 2>/dev/null
set -a && source .env && set +a
PYTHONUNBUFFERED=1 nohup .venv/bin/python -u -m app.cli serve --port 8099 > /tmp/autocaller.log 2>&1 &
disown

# 5. Verify
sleep 3 && curl -s http://127.0.0.1:8099/health     # expect: ok
bin/autocaller doctor                                 # all rows must be ✓
```

---

## Placing a test call

```bash
# (a) Phone must be in the allowlist. Field name is "phones" (NOT "allowed_phones") in the request body.
curl -s -X PUT http://127.0.0.1:8099/api/settings/allowed-phones \
  -H 'content-type: application/json' \
  -d '{"phones":["+14155551234"]}'

# (b) Enable live calls. Field name is "allowed" in the body.
curl -s -X PUT http://127.0.0.1:8099/api/settings/allow-live-calls \
  -H 'content-type: application/json' \
  -d '{"allowed":true}'

# (c) Ensure call_mode=twilio (not web).
curl -s http://127.0.0.1:8099/api/settings | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("call_mode"))'

# (d) Add the lead (use DB directly — CLI leads add may hang on interactive prompt).
set -a && source .env && set +a
.venv/bin/python -c "
import asyncio
from app.db import AsyncSessionLocal
from app.db.models import PatientRow
async def go():
    async with AsyncSessionLocal() as s:
        s.add(PatientRow(patient_id='LEAD-TEST', name='Test Person', phone='+14155551234',
                         firm_name='Test Firm', state='CA', email='test@example.com',
                         title='Managing Partner', practice_area='personal injury', tags=[]))
        await s.commit()
asyncio.run(go())
"

# (e) Fire the call
curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:8099/api/call/start \
  -H 'content-type: application/json' \
  -d '{"patient_id":"LEAD-TEST","mode":"twilio"}'
```

A `200` response with a `call` object means Twilio was dialed. Watch `/tmp/autocaller.log` for events.

---

## Inspecting a call afterwards

```bash
# List recent calls
bin/autocaller calls list --limit 10

# Show a specific call (full JSON including post-call capture fields)
bin/autocaller calls show <call_id>

# Print the transcript (speaker-tagged, chronological)
bin/autocaller calls transcript <call_id>

# Recording lives at:
ls app/audio/recordings/$(date +%Y/%m)/<call_id>.mp3

# If the transcript JSONB is empty but the MP3 exists (e.g. after a log wipe),
# recover via Whisper:
.venv/bin/python -c "
from openai import OpenAI
import os
c = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
with open('app/audio/recordings/YYYY/MM/<call_id>.mp3','rb') as f:
    tr = c.audio.transcriptions.create(model='whisper-1', file=f,
        response_format='verbose_json', timestamp_granularities=['segment'])
for s in tr.segments: print(f'[{s.start:6.2f}s] {s.text.strip()}')
"
```

---

## Critical gotchas (learned the hard way)

### 1. `DELETE /api/calls` with no query string WAS destructive
Old behaviour wiped every `call_logs` row. Fixed — the default now just clears the in-memory active-call marker. Destructive wipe requires `?confirm=wipe`. If you're on an older deploy, USE `POST /api/calls/clear-active` instead, or the wipe is irreversible.

### 2. The "single_patient_ready" scenario wipes the patients table at startup
If `system_settings.active_scenario_id` is non-null AND `patient_source='simulation'`, the daemon re-activates the scenario on every restart and calls `reset_with_patients([...])`, which deletes every row in `patients` and reseeds with the scenario's fixed patient. Before adding real leads, clear the scenario:

```bash
set -a && source .env && set +a && .venv/bin/python -c "
import asyncio
from app.db import AsyncSessionLocal
from app.db.models import SystemSettingsRow
from sqlalchemy import update
async def r():
    async with AsyncSessionLocal() as s:
        await s.execute(update(SystemSettingsRow).where(SystemSettingsRow.id==1).values(active_scenario_id=None))
        await s.commit()
asyncio.run(r())
"
```

### 3. Twilio Geographic Permissions block most international destinations
Calls to non-US numbers fail with SIP 480 / no-answer and zero ring time unless enabled in Twilio Console → **Voice → Settings → Geographic Permissions**. SMS has a **separate** permission page at **Messaging → Geographic Permissions** — an SMS region block manifests as Twilio error 21408. When diagnosing "didn't ring", check both.

### 4. `.env` values with spaces must be quoted
`source .env` is a shell script; `FOO=Acme AI` parses as `FOO=Acme` plus running `AI` as a command. Quote multi-word values: `SALES_REP_COMPANY="Acme AI"`.

### 5. Cloudflared quick tunnels are ephemeral
Every restart → a new subdomain. The `PUBLIC_BASE_URL` in `.env` must match the **current** tunnel URL, or Twilio callbacks (TwiML fetch + media-stream WS) silently fail and every call ends with `error_code=media_stream_timeout`. Grep `/tmp/cf.log` after every restart.

### 6. Media-stream handshake over cloudflared is slow
Initial WebSocket upgrade from Twilio → cloudflared → daemon can take 30–60s on a cold tunnel. The orchestrator's `wait_for_connection` timeout was bumped to 90s. If you see `media stream timed out` followed by a late `Twilio sent stop event`, that's the tunnel cold-starting; warm it up by making any curl request to `$PUBLIC_BASE_URL/health` before the first call.

### 7. Request body field names don't match the response field names
- Setting allowed phones: request body uses `phones`, response uses `allowed_phones`.
- Toggling live calls: request body uses `allowed`, response uses `allow_live_calls`.
- Mock mode: request body uses `enabled`, response uses `mock_mode`.
Don't assume symmetry.

### 8. The `/api/call/start` 409 has three causes
All return the same `"Call could not be started"` message:
- Another call is marked in-progress (check `/api/calls/active` — if stale, POST `/api/calls/clear-active`)
- `ALLOW_TWILIO_CALLS=true` env var not set, OR `allow_live_calls=false` in DB
- Phone number not in `allowed_phones` DB list
Read `tail /tmp/autocaller.log` immediately after the 409 — the specific reason is logged.

### 9. SMS fires automatically on several outcomes
After `no_answer`, `failed`, `callback_requested`, `completed`, the notification service sends an SMS to the lead. If you're running lots of test calls, you'll rack up many outbound SMS attempts. SMS content was updated to a generic autocaller template; verify current content with `.venv/bin/python -c "from app.services.twilio_sms_service import build_sms_message; print(build_sms_message('callback_info'))"`.

### 10. Cal.com without an API key → AI goes silent on booking
Without `CALCOM_API_KEY` + `CALCOM_EVENT_TYPE_ID`, `check_availability` returns `{slots: [], error: 'calendar_not_configured', fallback: 'offer_email_followup'}` and the prompt now instructs the AI to fall back to `send_followup_email` + `end_call(callback_requested)`. If you DO want live bookings, both must be set in `.env` and the daemon restarted.

---

## Safety rails — all three must align for a live call

1. **`ALLOW_TWILIO_CALLS=true`** in `.env` (env var, evaluated by `place_twilio_call`).
2. **`allow_live_calls=true`** in DB `system_settings` (set via `PUT /api/settings/allow-live-calls {"allowed": true}`).
3. **Phone in `allowed_phones`** list (set via `PUT /api/settings/allowed-phones {"phones": [...]}`).

When diagnosing "why is this call refused?", check all three.

---

## Triage playbook

### Symptom: `/api/call/start` returns 409
```bash
tail -30 /tmp/autocaller.log | grep -iE 'call|allow|allowed|mock|error'
curl -s http://127.0.0.1:8099/api/calls/active
curl -s http://127.0.0.1:8099/api/settings | jq '{allow_live_calls, allowed_phones, mock_mode, call_mode}'
curl -s -X POST http://127.0.0.1:8099/api/calls/clear-active   # safe: does not wipe logs
```

### Symptom: Call places but phone doesn't ring
```bash
# Twilio's view of the call
.venv/bin/python -c "
from twilio.rest import Client; import os
c = Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])
for call in c.calls.list(to='+YOURPHONE', limit=3):
    print(call.start_time, call.sid, call.status, f'{call.duration}s', call.answered_by, call.price)
# Any Twilio alerts?
for ev in c.monitor.v1.alerts.list(limit=5):
    print(ev.date_created, ev.error_code, (ev.alert_text or '')[:140])
"
```
Common causes: Geo permissions not enabled, AMD mis-classifying carrier voicemail as human (duration=0 + answered_by=human is the signature), your phone is in DND, or Twilio trial-account restrictions.

### Symptom: AI goes silent mid-call after tool call
- Check if `check_availability` or `book_demo` returned an error: `grep -A2 'function_call\|check_avail\|book_demo' /tmp/autocaller.log`
- The prompt now has a "never go silent after a tool call" rule and an email-fallback path, but if it regresses, reinforce that in `app/prompts/attorney_cold_call.py`.

### Symptom: Media stream timeout, call ends with `disconnected`
- Cold cloudflared tunnel. Warm it: `curl $PUBLIC_BASE_URL/health`
- Check TwiML URL matches your current tunnel: `curl $PUBLIC_BASE_URL/api/twilio/twiml/testid | head -5`
- Check Twilio actually fetched TwiML: `grep 'Twilio fetched TwiML' /tmp/autocaller.log`

### Symptom: Everything looks fine but dispatcher never picks a lead
- `autocaller dispatcher status` — inspect `recent_decisions`
- Common: `no_candidate` means (a) no leads in DB, (b) every lead has `attempt_count >= max_attempts` (default 3), (c) every lead is within cooldown (default 6h since last attempt), or (d) every lead is outside its state's per-state calling window.
- Zap retry state: `UPDATE patients SET attempt_count=0, last_attempt_at=NULL, last_outcome=NULL` via psql.

---

## Where everything lives

- **Project root**: `/home/pranav/autocaller`
- **CLI**: `bin/autocaller` (wraps `.venv/bin/python -m app.cli`)
- **Daemon log**: `/tmp/autocaller.log` (tail it during any call)
- **Tunnel log**: `/tmp/cf.log`
- **Recordings**: `app/audio/recordings/YYYY/MM/<call_id>.mp3`
- **AI prompt**: `app/prompts/attorney_cold_call.py` — edit `SYSTEM_PROMPT_TEMPLATE` to change the pitch
- **AI tools**: same file, `TOOLS` list
- **Call orchestration**: `app/services/call_orchestrator.py` — tool dispatch in `_handle_function_call`
- **Cal.com client**: `app/services/calcom_service.py`
- **Dispatcher (polling + gating)**: `app/services/dispatcher.py`
- **DB models**: `app/db/models.py` (table `patients` holds leads; `call_logs` holds calls)
- **Migrations**: `alembic/versions/` (head is `r9s0t1u2v3w4` — attorney columns)

---

## Don'ts

- **Don't commit `.env`.** It's in `.gitignore`. If you accidentally stage it, unstage immediately.
- **Don't run `DELETE /api/calls?confirm=wipe`** unless the user explicitly asks to wipe call history.
- **Don't change `TWILIO_FROM_NUMBER`** without confirming the new number is voice-enabled and has the right geo permissions.
- **Don't test the call-pipeline during business hours** of a real cold-calling campaign; the dispatcher may pick up your test phone as a lead if it ends up in the `patients` table.
- **Don't kill the daemon mid-call**; it will leave Twilio holding an orphan call until its own timeout fires. Clear active calls via the API first.
- **Don't assume Colombia/India/etc. are reachable** without verifying both Voice and SMS geo permissions in Twilio console.
- **Don't reinvent lead import** — `bin/autocaller leads import <csv>` handles upsert, phone normalisation, skip-invalid, and `--dry-run`.

---

## New CLI commands (v1.1) — use these before falling back to curl/psql

| command | purpose |
|---|---|
| `autocaller system on\|off\|status` | Master kill switch |
| `autocaller mock on <phone>\|off\|status` | Mock-mode redirect |
| `autocaller allowlist list\|add\|remove\|clear\|set-from-leads [--state --dm-only --limit]` | Phone allowlist |
| `autocaller dispatcher batch <N>` | Start dispatcher with auto-stop at N calls |
| `autocaller dispatcher clear-active` | Clear stuck active-call marker |
| `autocaller calls judge <id>\|--all-pending` | Run LLM judge on a call |
| `autocaller followups list [--action --owner --disposition --within]` | GTM follow-up queue |
| `autocaller followups show <id>` | Single-call follow-up JSON |
| `autocaller followups send-voicemail <id> [--dry-run]` | Fire VM / no-reach follow-up email for one call (gated by `ALLOW_VOICEMAIL_EMAIL`) |
| `autocaller followups backfill-voicemails [--since-days N --limit N --live]` | Batch-send VM / no-reach follow-up emails (default `--dry-run`) |
| `autocaller voice status\|openai\|gemini\|set <p>` | Switch realtime voice backend default |
| `autocaller dispatcher cooldown [<secs>]` | Read / set inter-call cooldown in seconds |
| `autocaller ivr status\|on\|off` | Toggle LLM-driven phone-tree navigation (DTMF via Twilio) |
| `autocaller leads set-language <id> en\|es` | Set outbound language for a lead (en/es prompt + voice seed) |
| `autocaller leads sync-mission --tiers=A,B,C --dm-threshold=4 --limit=500` | Pull fresh PI-firm leads from Mission Control. See `docs/MISSION_CONTROL_SYNC.md`. Run when dispatcher logs `no_candidate: No eligible patients in queue`. |
| `autocaller leads list --language=es` | Filter leads by language |
| `autocaller call <lead_id> --voice=openai\|gemini` | Per-call backend override |
| `autocaller calls list --provider=openai\|gemini` | Filter history by backend |
| `autocaller carrier status` | Show **both** telephony carriers (Twilio + Telnyx): masked SID/key, account name+type, reachability, from-number, balance. Marks whichever is the default. Pulls live data. Also visible on `/system` page with a switcher. |
| `autocaller carrier twilio\|telnyx\|set <name>` | Switch default telephony carrier. Persisted in `system_settings.default_carrier`. |
| `autocaller call <lead> --carrier=twilio\|telnyx` | Per-call carrier override (overrides DB default for this call only). |
| `autocaller calls list --carrier=twilio\|telnyx` | Filter call history by which carrier placed each call. |
| `autocaller calls takeover <call_id> [--off]` | Flip human-takeover on a live call — mutes AI + cancels in-flight response. UI-side: `ActiveCallOverlay` has a Take over / Hand back button that ALSO opens the browser mic and pipes it to Twilio via the `/ws/listen/{call_id}` WebSocket (reused for inbound audio). Wear headphones or the call will echo. |
| `autocaller email status` | Show email transport (Resend vs SMTP), FROM, default recipient, BCC, reply-to, `ALLOW_VOICEMAIL_EMAIL` gate. Run this first when troubleshooting follow-up delivery. |
| `autocaller email test [--to ...]` | Plain test email through whichever transport is active. Defaults recipient to `EMAIL_NOTIFICATION_RECIPIENT`. |
| `autocaller email send-onepager --to ... [--name --firm --note --rep-* ]` | Manually fire the post-call one-pager template (same one the AI sends mid-call via `send_followup_email`). |
| `autocaller email send-vm-followup --to ... [--first-name ...] [--no-vm]` | Manually fire the VM / no-reach follow-up template against any address — no `call_id` needed. Gated by `ALLOW_VOICEMAIL_EMAIL`. |
| `autocaller email send-consult --to ... --name ... --slot ... [--firm --notes]` | Manually fire the consult-booking confirmation (same template the Cal.com booking flow sends). |
| `autocaller comms list [--firm --channel --since --status --q --limit --raw]` | Outbound communications feed (calls + voicemail + sms + email). Unions `call_logs` (channel derived from `voicemail_left`), `email_logs`, `sms_logs`. Same data the `/comms` UI page shows. `--firm <pif_id>` narrows to one firm; `/firms/{pif_id}` shows the same timeline inline. |
| `autocaller comms show <kind:id>` | Show one comm as JSON. Kinds: `call:` (or for voicemail too — same call_id), `email:`, `sms:`. |
| `autocaller listening brief [--version N]` | Print the Mission Control mindset brief markdown from `http://127.0.0.1:8001/api/listening`. Read-only. |
| `autocaller listening search "<q>" [--type T] [--who W] [--limit N]` | Search extracted listening insights by query, type, and buyer persona. |
| `autocaller listening quotes --cluster <cluster> [--limit 5]` | Show direct quotes for one listening insight cluster. |
| `autocaller listening sources` | Show listening source name, kind, last poll time, and computed stale flag. |
| `autocaller listening prep <firm-or-name>` | Build a pre-call one-pager from local `patients`/`firm_contacts`, top matched listening insights, and one gateway call. Read-only. |
| `autocaller contacts backfill` | Populate `firm_contacts` from PIF Stats `leadership[]` + the patient DM. Idempotent. Run once before any `sequences start`. |
| `autocaller contacts list [--firm <pif_id>]` | List firm_contacts roster. |
| `autocaller sequences preview <contact_id>` | Render the four-email sequence for one contact, with their real Yelp quote injected. Read-only. |
| `autocaller sequences start <contact_id>` | Start the 4-step sequence (one contact at a time, by design). Idempotent — second start returns 409. Sends are gated by `ALLOW_SEQUENCE_SEND=true`. UI: `/sequences` page has the same flow with a forced "I've reviewed all drafts" checkbox before the Start button enables. |
| `autocaller sequences list [--status active\|paused\|completed]` | List sequence rows + step state. |
| `autocaller lead-gen policy\|recommend\|batches\|show\|approve\|observe\|observations\|propose` | Cybernetic lead-generation loop for Precise Imaging. Recommends bounded batches, requires approval, and creates lightweight operator action-center approvals immediately when selected email sequences are queued; drafts compose lazily when an action is opened. Automatic observations capture sends, failures, replies, clicks, bookings, call dispositions, cancellations, and reschedules. Use `lead-gen observations summary --since 7d` for the weekly learning KPI. UI: `/lead-gen`. Concept doc: `docs/CYBERNETIC_LEAD_GEN_CONCEPT.md`. |
| `autocaller actions list\|show\|policy-check\|execute` | Durable Possible OS action execution queue. Supported high-risk actions must be policy-checked and use narrow executors. |
| `autocaller actions list [--scheduled]` | List durable action records. `--scheduled` shows future approved scheduled sends ordered by send time. |
| `autocaller actions scheduler-status` | Show daemon scheduled-action loop status, last tick, pending scheduled count, and due count. |
| `autocaller actions send-approved-lead-gen-draft --item=... --subject=... --body=... [--at "09:30 PT" --no-execute]` | Create and optionally execute an exact approved lead-gen email draft action. With `--at`, schedule it instead of sending now. Do not use arbitrary shell email sends for master-agent execution. |
| `autocaller actions send-email --mode=test --to=... --subject=... --body=... [--at "2026-06-11T09:30:00-07:00" --no-execute]` | Create and optionally execute a regular durable email action. With `--at`, create an approved scheduled action and do not send immediately. |
| `autocaller actions send-test-email --to=... [--subject ... --body ... --no-execute]` | Convenience alias for `send-email --mode=test`. Use this to validate the durable execution path. |
| `autocaller todos list\|add\|update\|delete` | DB-backed editable project backlog. Use this or the `/todos` UI for new active backlog items; do not add new todo markdown files. |
| `autocaller ideas list\|add\|edit` | Simple future product, marketing, and GTM idea capture. Backed by the todos API/table with `area=ideas`; use `add -` or `edit <id> -` for multiline stdin. UI: `/ideas`. |
| `autocaller outreach campaigns create --post-slug=...` | Spin up a new LLM-composed blog-post outreach campaign. Snapshot of post metadata + excerpts is frozen on the row so every recipient sees the same context. |
| `autocaller outreach campaigns list [--status=...]` / `show <id>` | Inspect campaigns and per-status send counts + open/click totals. |
| `autocaller outreach audience add --campaign=N --pif-ids=A,B\|--contact-ids=A,B [--exclude-recent-days=14]` | Expand firms into emailable contacts; dedupes against the campaign and skips anyone emailed in the last N days. |
| `autocaller outreach compose --send=N [--regenerate]` / `compose-all --campaign=N` | Call the openclaw LLM gateway (skill: `blog-outreach-composer`) to render subject + preheader + body_html + plaintext + reasoning. Cached on the row — second compose is a no-op without `--regenerate`. |
| `autocaller outreach preview --send=N [--html-out=path]` | Render the EXACT bytes that will be sent (full HTML doc with chrome + tracking pixel + signature, plaintext signature appended). Use `--html-out` to open in a browser. |
| `autocaller outreach next --campaign=N` | Step-through helper: show the next send to review (composed first, then pending). |
| `autocaller outreach send --send=N [--yes]` / `send-batch --campaign=N --limit=N [--auto]` | Fire the email via Resend. Real side effect — confirm prompts unless `--yes`/`--auto`. |
| `autocaller outreach skip --send=N --reason=...` | Mark a send as skipped (won't surface in `next`, won't be sent). |
| `autocaller outreach edit --send=N [--subject ...] [--body-html-file ...] [--plaintext-file ...]` | Operator hand-edits over the composed body. Edited fields must still contain literal `{{TRACKED_POST_URL}}`. |
| `autocaller outreach stats --campaign=N` / `events --campaign=N [--send=N]` | Per-status counts + open/click events. |

## Quick-reference: REST endpoints actually used

| method | path | body field(s) |
|---|---|---|
| GET | `/health` | — |
| GET | `/api/status` | — |
| GET | `/api/settings` | — |
| PUT | `/api/settings/allow-live-calls` | `allowed: bool` |
| PUT | `/api/settings/allowed-phones` | `phones: string[]` |
| PUT | `/api/settings/call-mode` | `call_mode: "twilio"\|"web"` |
| PUT | `/api/settings/mock-mode` | `enabled: bool` |
| PUT | `/api/settings/voice` | `provider: "openai"\|"gemini", model?: str` |
| PUT | `/api/settings/dispatcher/cooldown` | `cooldown_seconds: int` |
| PUT | `/api/settings/ivr-navigate` | `enabled: bool` |
| POST | `/api/call/start` | `patient_id: str, mode: "twilio", voice_provider?: str` |
| GET | `/api/calls/active` | — |
| POST | `/api/calls/clear-active` | — |
| POST | `/api/calls/{call_id}/takeover` | `enabled: bool` — mute AI + accept operator mic frames over `/ws/listen/{call_id}` |
| DELETE | `/api/calls?confirm=wipe` | ⚠ destructive |
| GET | `/api/dispatcher/status` | — |
| POST | `/api/dispatcher/toggle` | `enabled: bool` |
| GET | `/api/calls` | `?limit=25&offset=0` |
| GET | `/api/calls/{call_id}` | — |
| POST | `/api/resend/webhook` | Resend public webhook. No CLI wrapper; verifies `svix-*` headers with `RESEND_WEBHOOK_SECRET`, updates `email_logs`, creates lead-gen observations, and pauses bounced/delayed/failed/complained sequences. |

Full OpenAPI: `curl http://127.0.0.1:8099/openapi.json | jq .paths`.

### Outreach endpoints

| method | path | notes |
|---|---|---|
| POST | `/api/outreach/campaigns` | create campaign (snapshot of post is frozen on the row) |
| GET | `/api/outreach/campaigns[?status=]` | list |
| GET | `/api/outreach/campaigns/{id}` | detail + stats |
| POST | `/api/outreach/campaigns/{id}/audience` | `{contact_ids[]?, pif_ids[]?, exclude_recent_days?}` |
| GET | `/api/outreach/campaigns/{id}/sends[?status=]` | list recipients |
| GET | `/api/outreach/campaigns/{id}/next` | step-through head |
| POST | `/api/outreach/sends/{id}/compose` | `{regenerate, model?}` — calls openclaw gateway |
| GET | `/api/outreach/sends/{id}/preview` | wrapped subject + html + plaintext that send_now would post |
| POST | `/api/outreach/sends/{id}/send` | real Resend call |
| POST | `/api/outreach/sends/{id}/skip` | `{reason}` |
| POST | `/api/outreach/sends/{id}/edit` | `{subject?, body_html?, plaintext?, by?}` |
| GET | `/api/outreach/blog-posts` | known slugs (for the UI builder) |
| GET | `/t/o/{token}.gif` | **public, no auth** — 1×1 open-pixel |
| GET | `/t/c/{token}` | **public, no auth** — 302 to canonical blog URL, logs click |

The `/t/*` routes are exempt from the daemon's session middleware (see
`_AUTH_EXEMPT_PREFIXES` in `app/main.py`) — email clients can't carry the
session cookie. They must be reachable at `OUTREACH_PUBLIC_BASE_URL` from
the open internet, or tracking links in recipient inboxes go nowhere.
