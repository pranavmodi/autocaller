# Attorney Cold-Call Autocaller

Headless, CLI-operable outbound voice system that cold-calls US personal-injury
attorneys, runs a discovery conversation, identifies the firm's biggest
operational pain point (case intake, medical-records retrieval, lien processing,
demand-letter generation, etc.), and books a demo via Cal.com.

Built by adapting a FastAPI + Twilio + OpenAI-Realtime outbound-call engine
originally designed for a medical-imaging scheduler.

## Quick start

```bash
cd /home/pranav/OutboundVoiceAI
.venv/bin/pip install -r requirements.txt
bin/autocaller config init              # interactive .env wizard
.venv/bin/alembic upgrade head          # DB migrations
bin/autocaller doctor                   # must be all ✓ before live calls
bin/autocaller serve                    # start daemon (separate terminal / tmux)
bin/autocaller leads import leads.csv   # bulk-load leads
bin/autocaller dispatcher start         # begin auto-calling
bin/autocaller calls list               # review what happened
```

## Documentation

- **[docs/cli.md](docs/cli.md)** — full CLI reference + AI-agent operator's guide.
  Command schemas, failure modes, recipes, REST API, DB schema.
- Legacy docs under `docs/` (`system-overview.md`, `requirements.md`, etc.)
  describe the original medical-imaging build and are partly superseded; read
  them for architectural context only.

## Architecture overview

Two processes:

- **Daemon** (`autocaller serve`): long-running FastAPI app on port 8000.
  Hosts the Twilio webhooks, bridges Twilio media streams to OpenAI Realtime,
  runs the dispatcher polling loop, and persists to Postgres.
- **CLI** (`bin/autocaller`): thin client. Most commands hit the daemon on
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
