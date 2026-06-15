# Possible OS

Headless, CLI-operable outbound voice system that cold-calls US personal-injury
attorneys, runs a discovery conversation, identifies the firm's biggest
operational pain point (case intake, medical-records retrieval, lien processing,
demand-letter generation, etc.), and books a demo via Cal.com.

Built by adapting a FastAPI + Twilio + OpenAI-Realtime outbound-call engine
originally designed for a medical-imaging scheduler.

The Precise Imaging lead-generation workflow is now being implemented as a
cybernetic function: the system recommends a bounded batch, executes approved
email sequences, observes replies/delivery feedback/bookings, writes those
observations back to durable state, and proposes policy/copy changes against
the target metric of booked qualified conversations. See
`docs/CYBERNETIC_LEAD_GEN_CONCEPT.md` for the conceptual design,
the `/todos` UI or `bin/possibleos todos ...` for the active DB-backed backlog,
and `docs/LEAD_GEN_CYBERNETIC_TECHNICAL.md` for implementation details. Zoho Mail
can remain the mailbox provider: the system reads inbound
replies over Zoho IMAP when `ZOHO_IMAP_USER` and `ZOHO_IMAP_PASSWORD` are
configured. Matched replies create operator notifications in the Possible OS UI
with the stimulus email, proposed classification, paused sequence context, and
suggested next action. The operator can edit the draft in the action center and
send it back in the same thread through the approved send action.

## Quick start

```bash
cd /home/pranav/possibleos
.venv/bin/pip install -r requirements.txt
bin/possibleos config init              # interactive .env wizard
.venv/bin/alembic upgrade head          # DB migrations
bin/possibleos doctor                   # must be all ✓ before live calls
bin/possibleos serve                    # start daemon (separate terminal / tmux)
bin/possibleos leads import leads.csv   # bulk-load leads
bin/possibleos dispatcher start         # begin auto-calling
bin/possibleos calls list               # review what happened
```

## Documentation

- **[docs/cli.md](docs/cli.md)** — full CLI reference + AI-agent operator's guide.
  Command schemas, failure modes, recipes, REST API, DB schema.
- **[docs/CYBERNETIC_LEAD_GEN_CONCEPT.md](docs/CYBERNETIC_LEAD_GEN_CONCEPT.md)** —
  conceptual design of the lead-generation cybernetic function.
- **`/todos` UI and `bin/possibleos todos ...`** — DB-backed active backlog.
- **[docs/LEAD_GEN_CYBERNETIC_TECHNICAL.md](docs/LEAD_GEN_CYBERNETIC_TECHNICAL.md)** —
  current lead-gen implementation, APIs, tables, services, and operations.
- Legacy docs under `docs/` (`system-overview.md`, `requirements.md`, etc.)
  describe the original medical-imaging build and are partly superseded; read
  them for architectural context only.

## Architecture overview

Two processes:

- **Daemon** (`possibleos serve`): long-running FastAPI app.
  Hosts the Twilio webhooks, bridges Twilio media streams to OpenAI Realtime,
  runs the dispatcher polling loop, and persists to Postgres.
- **CLI** (`bin/possibleos`): thin client. Most commands hit the daemon on
  loopback REST; bulk lead import/export reads/writes the DB directly.

```
┌─────────┐   REST     ┌──────────────────┐   Twilio REST    ┌─────────┐
│   CLI   │──────────▶ │   FastAPI        │ ───────────────▶│ Twilio  │
│ (typer) │            │   daemon         │ ◀───────────────│ (PSTN)  │
└─────────┘            │                  │   media WS       └────┬────┘
                       │  Dispatcher ─┐   │                       │
                       │  Orchestrator│   │   bidi audio WS       │
                       │  CalComSvc   │   │ ◀─────────────────────┘
                       └──────┬───────┘   │
                              │           │        OpenAI Realtime
                              ▼           ▼ ◀─────────────────────┐
                          Postgres   Cal.com API           ┌──────┴──────┐
                                     (book demo)           │   OpenAI    │
                                                           └─────────────┘
```

## Safety rails

Three independent gates protect against unwanted outbound calls:

1. `ALLOW_TWILIO_CALLS=true` in `.env`.
2. `allow_live_calls=true` in DB `system_settings`.
3. `allowed_phones` list in DB `system_settings` — numbers not on the list are rejected.

See §9 of `docs/cli.md` for the test-call recipe.

## Branch

Current work is on `feature/attorney-autocaller`. The parent branch
`feature/automate_voice_calls` retains the medical-imaging orchestrator.

## Operations

- Logs: daemon stdout (redirect or tmux-capture).
- Recordings: `app/audio/recordings/YYYY/MM/{call_id}.mp3`.
- DB schema: see `app/db/models.py` and §13 of `docs/cli.md`.
- Prompt + AI tools: `app/prompts/attorney_cold_call.py`.
- Cal.com integration: `app/services/calcom_service.py`.
