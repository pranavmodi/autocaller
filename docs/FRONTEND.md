# Autocaller Frontend — Feature List (Minimal)

A read-mostly web UI for observability. The CLI stays the source of truth
for operations; the frontend exists so Pranav can glance at what's happening
without opening a terminal.

## Design principles

1. **Observability > control.** Every mutation is available via CLI/REST;
   the UI exposes a narrow subset of mutations only when obviously safe
   (toggle dispatcher, clear active-call marker). No CRUD screens.
2. **Minimal, opinionated.** Five screens total. No settings pages, no
   lead editor, no prompt editor. You want those, open the repo.
3. **Live by default.** Anything that changes in the backend (active call,
   transcript, dispatcher state) streams in real-time. No manual refresh.
4. **Mobile-first.** Pranav checks this between meetings on a phone.
   Single-column, touch-friendly, readable at a glance.
5. **One auth bar.** The daemon is behind `autocaller.getpossibleminds.com`;
   add HTTP basic auth in nginx. No in-app user system.

---

## The five screens

### 1. `/` — Now
What's happening *right now*. Single screen, glanceable in 2 seconds.

- **Dispatcher pill** — running / stopped / blocked — with latest decision
  reason ("no_candidate: all leads in cooldown").
- **Active call card** (appears only when a call is live):
  - Lead name, firm, state, phone, call duration ticker
  - Live transcript streaming word-by-word (alternating AI / lead bubbles)
  - Outcome indicator if the AI has already called `end_call`
  - "End this call" button — safe, wraps the Twilio hangup + clear-active
- **Next up** — top 3 eligible leads the dispatcher is about to call, in
  priority order, with a "why this one" line ("decision-maker, never called").
- **Last 3 calls** — outcome emoji + firm + duration + "open transcript" link.
- **Toggle dispatcher** — one switch. Matches CLI `dispatcher start/stop`.

### 2. `/calls` — Call history
A table. Nothing fancy.

- Rows: `time, firm, state, outcome, duration, interest_level, demo_booked?`
- Outcome-pill color coding: green=demo_scheduled, amber=callback, red=failed, grey=voicemail/no_answer.
- Filter by: outcome, state, date range, "demos only".
- Click row → drawer on the right with full call detail (see screen 3).
- Export button → same CSV the CLI produces.
- Infinite scroll, 50 rows at a time.

### 3. `/calls/:id` — Single call (or side-drawer from `/calls`)
Everything about one call.

- Top: firm, lead name, phone, outcome pill, duration, started_at.
- **Recording player** — native HTML5 audio, loads the MP3 from disk.
- **Transcript** — speaker-tagged, scrollable, timestamped; clicking a line
  seeks the audio player to that moment.
- **Structured capture** (the fields the AI set via `end_call` args):
  pain_point_summary, interest_level (1-5), is_decision_maker, was_gatekeeper,
  gatekeeper_contact, demo_booking_id + meeting_url if set.
- **Cal.com demo panel** (if `demo_scheduled`) — booking time, meeting URL,
  cancel/reschedule links pulled from Cal.com API.
- "Retry this lead in X hours" quick action — bumps `last_attempt_at` back.

### 4. `/pipeline` — Lead queue
A visible representation of who's getting called next and why.

- Kanban-lite columns:
  - **Up next** (eligible + within calling window, sorted by priority)
  - **Cooling down** (called recently, waiting on min_hours_between)
  - **Exhausted** (attempt_count >= max_attempts)
  - **Opted out / DNC**
- Card per lead: name, firm, state, title, last_outcome, attempt_count,
  "next eligible at".
- Filter by state, practice area, title (decision-maker only).
- Click card → show full lead record + call history for that lead.
- Bulk actions: reset retry state on selected, remove from queue. Both
  confirm-to-proceed; nothing destructive lands on a click.

### 5. `/health` — System status
The `doctor` command as a page. Visible whether the plumbing is OK.

- Green/red row per check:
  - Postgres reachable + migration head matches code
  - OpenAI Realtime key valid + model accessible
  - Twilio auth valid + from-number owned
  - Cal.com auth valid + event type resolves
  - PUBLIC_BASE_URL resolves + cert valid + expiring-in-X-days
  - Nginx / daemon / cloudflared (if in use) process alive
- Daemon uptime, last restart, last crash reason.
- Last 50 log lines from `/tmp/autocaller.log`, filterable by level.
- Funnel stats for the last 7 days: dials → connects → conversations →
  demos, with conversion rates between each.

---

## What explicitly does NOT exist in v1

To keep the surface tight:

- **No settings UI.** Change `sales_context`, `calcom_config`, `allowed_phones`
  via CLI or `.env`. UI-exposed settings drift from `.env` and cause bugs.
- **No lead editor / importer.** Use `autocaller leads import leads.csv`.
- **No prompt editor.** The prompt lives in the repo. Edits go through git.
- **No user / role system.** One operator, basic auth at the edge.
- **No CRM sync UI.** When CRM integration lands, it's a backend cron;
  UI just shows "last synced at".
- **No charts / graphs / dashboards beyond the funnel on `/health`.**
  If you want analytics, export CSV and pivot in whatever tool you like.

---

## Tech shape (proposal, not prescription)

- **Single-page React** served as static files from FastAPI's `static/`
  mount, OR a tiny Next.js if Pranav wants SSR. No API gateway needed —
  the existing REST + WebSocket suffice.
- **WebSocket channel** `/ws/dashboard` already exists in the backend and
  broadcasts queue_update, decision, call_started, call_ended, transcript
  deltas. Reuse directly.
- **Styling**: Tailwind + shadcn/ui (same stack the archived frontend used
  — keeps us in familiar territory).
- **Hosting**: same nginx, same domain, served from the daemon.
- **Size budget**: <200KB JS bundle, no heavy charting libs, no router
  beyond file-based.

---

## Phased build

### Phase 1 (1-2 days) — "Now" screen only
Just `/` and `/health`. Pranav can tell if the system is doing something and
if it's healthy. Everything else stays CLI.

### Phase 2 (2-3 days) — History + Single call
`/calls` table and `/calls/:id` detail with transcript + recording playback.
This is where the real value lives — reviewing calls without running
`bin/autocaller calls transcript <id>` each time.

### Phase 3 (2-3 days) — Pipeline + funnel stats
`/pipeline` queue view and the 7-day funnel block on `/health`. Useful once
there are >20 leads and >50 calls to reason about.

Stop after Phase 3 unless a concrete need drives more. The goal is not a
product, it's a pane of glass.
