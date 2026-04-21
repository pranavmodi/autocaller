# CLAUDE.md — project rules for Claude Code (and any AI agent editing this repo)

## Golden rule — CLI parity for every feature

**Every backend capability, setting, or operator action MUST have a CLI command.** The UI is for observability; the CLI is the operator contract. Anything exposed only in the UI or via raw REST becomes invisible to headless agents, cron jobs, shell scripts, CI, and anyone comfortable on a terminal — which includes *us*.

Whenever you add a feature:

1. **Build the backend** — service code, REST endpoint, DB migration, etc.
2. **Add a CLI wrapper** in `app/cli.py` that drives it. Prefer a top-level group for a new domain (`system`, `mock`, `allowlist`, `followups`, …); subcommands for actions. Use REST on loopback when the daemon is the source of truth; hit the DB directly only for bulk / offline operations.
3. **Update `docs/cli.md`** — the reference agents and humans read. At minimum add a row in the "New-command reference" table in §3; add a recipe in §10 if the command enables a new workflow.
4. **Update the skill** at `.claude/skills/autocaller/SKILL.md` **and** sync to `/root/.openclaw/workspace/skills/autocaller/SKILL.md` (or `cp` between them). The skill is what other AI agents load to know the system. If you added a command the skill doesn't mention, the next agent won't find it.
5. **Update the vision / feature docs** in `docs/` where the change is material — `VISION.md`, `SELF_IMPROVEMENT.md`, `DISPOSITIONS.md`, `FRONTEND.md`, `SIMULATED_RECEIVER.md`, `VOICE_PROVIDERS.md`.

Concrete examples of features that **must** have CLI commands, not just REST:
- Global on/off switches (`system on/off`, `mock on/off`)
- Safety rails (`allowlist add/remove/list/clear`)
- Dispatcher control (`dispatcher batch N`, `dispatcher clear-active`)
- Judge / post-call review (`calls judge <id>`, `calls judge --all-pending`)
- GTM pipeline actions (`followups list`, `followups show`)
- Lead ingestion (`leads sync-mission`, `leads import`)
- Configuration (`config show`, `config init`)
- Voice-backend selection (`voice openai|gemini|status`, per-call `call <id> --voice=…`, `calls list --provider=…`)
- IVR phone-tree navigation (`ivr on|off|status`)

If the functionality is genuinely UI-only (e.g. in-browser audio playback of a live call), document that exception in both `docs/cli.md` §11 and `SKILL.md`.

## Why

This repo is a headless outbound BD agent. It runs unattended. Over time the operator will be an AI or a shell script more often than a human pointing a mouse. The CLI is the stable, scriptable, regression-testable surface. REST alone is too low-level; UI alone is unscriptable.

A reasonable heuristic: if someone three months from now had only the CLI and `docs/cli.md`, could they operate the system end-to-end? If no, you missed something.

## Other standing rules

- **Keep safety rails explicit.** `ALLOW_TWILIO_CALLS`, `allow_live_calls`, `allowed_phones`, `mock_mode`, `system_enabled` — every new risk vector needs a gate of comparable clarity.
- **Never auto-start the dispatcher on daemon boot.** Restarts must not trigger outbound calls. Explicit operator action only.
- **Prompt change protocol.** Every prompt change must: (1) bump `PROMPT_VERSION` in `app/prompts/attorney_cold_call.py`, (2) `git commit` with a descriptive message, (3) `git push`, (4) restart the backend. No prompt change ships without all four steps. This ensures every live call's `prompt_version` traces to a committed, pushed revision.
- **LLM-first for information extraction.** Prefer structured-output LLM calls over regex for classifying titles, states, phones, dispositions, etc. Regex is acceptable only for fast pre-filters (e.g., the IVR-phrase detector in `transfer_service.py`).
- **Judge every completed call.** `app/services/judge.py` runs a background loop; new outcome types need to be added to its rubric.
- **Record the rendered prompt on every call log** (`prompt_text` + `prompt_version` + `tools_snapshot`). Post-hoc debugging depends on this.
- **Commit discipline**: descriptive commit message, Co-Authored-By Claude on every commit.
- **Never restart the daemon while a call is in progress.** Killing `app.cli serve` mid-call drops the OpenAI/Gemini WS, drops the Twilio/Telnyx media stream, and leaves the carrier holding an orphan leg that only times out later. Before any `pkill`/`kill -f app.cli` or daemon swap, check:
  1. `curl -s http://127.0.0.1:8099/api/calls/active` — if `active: true`, **wait**.
  2. `sudo -u postgres psql -d autocaller -c "SELECT call_id, firm_name, started_at FROM call_logs WHERE ended_at IS NULL AND started_at > now() - interval '10 minutes';"` — active marker may be stale; recent `ended_at=NULL` rows are authoritative.
  If an operator is listening via `/ws/listen/{call_id}`, the restart also cuts their audio. New code can wait — queue the restart for after the call completes.
