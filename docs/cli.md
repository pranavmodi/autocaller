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
| `calls judge <call_id>` | Run the LLM judge on one call (scores 0-10, assigns GTM disposition). |
| `calls judge --all-pending` | Backfill-judge every un-judged completed call. ~$0.02 each with gpt-4o-mini. |
| `followups list [--action=... --owner=... --disposition=... --within=14]` | Show calls that need human or automated follow-up, sorted by due date. |
| `followups show <call_id>` | JSON focus view for a single follow-up. |
| `leads sync-mission [--tiers=A,B --dm-threshold=5]` | LLM-driven import of PI-firm contacts from Mission Control. |
| `voice status` | Show the current default realtime voice backend (openai or gemini) + model. |
| `voice openai [--model=…]` / `voice gemini [--model=…]` / `voice set <p> [--model=…]` | Switch the default backend for subsequent calls. Stored in DB. |
| `call <lead_id> --voice=openai\|gemini` | Per-call override: pin this specific call to a provider regardless of the default. |
| `calls list --provider=openai\|gemini` | Filter history by which backend handled each call. |

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

### Recipe: "stop all calling now"
```bash
bin/autocaller dispatcher stop       # pauses dispatching; in-flight call finishes
# to force-end an active call:
curl -X DELETE http://127.0.0.1:8000/api/calls    # drops the active_call marker
# or nuke the daemon:
tmux kill-session -t autocaller
```

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
| GET  | `/api/statistics/today` | |
| POST | `/api/settings/allow-live-calls` | body `{"allowed": true}` |
| POST | `/api/settings/allowed-phones` | body `{"allowed_phones": ["+1..."]}` |
| POST | `/api/twilio/twiml/{stream_id}` | Twilio webhook — do **not** call manually |
| POST | `/api/twilio/status` | Twilio status callback |
| POST | `/api/twilio/recording-status/{call_id}` | Twilio recording callback |

An agent that doesn't want to shell out can drive the system entirely via
these JSON endpoints. The CLI commands are thin wrappers around them, with
the single addition of the bulk `leads import` / `calls export` paths which
hit the DB directly.

---

## 12. Common failure modes and fixes

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

## 13. Data model cheat sheet (for agents composing queries)

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

## 14. The AI's system prompt (what the caller actually says)

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

## 15. Commit hygiene

This codebase is on branch `feature/attorney-autocaller`. Don't push to `main`
until you've done at least one successful live demo-booking call end-to-end
(`doctor` green + one `outcome=demo_scheduled` in `calls list`).

When asking the user to commit, describe the change concretely ("added X
command"; don't say "updated CLI").
