# CLAUDE.md — project rules for Claude Code (and any AI agent editing this repo)

## Golden rule — CLI parity for every feature

**Every backend capability, setting, or operator action MUST have a CLI command.** The UI is for observability; the CLI is the operator contract. Anything exposed only in the UI or via raw REST becomes invisible to headless agents, cron jobs, shell scripts, CI, and anyone comfortable on a terminal — which includes *us*.

Whenever you add a feature:

1. **Build the backend** — service code, REST endpoint, DB migration, etc.
2. **Add a CLI wrapper** in `app/cli.py` that drives it. Prefer a top-level group for a new domain (`system`, `mock`, `allowlist`, `followups`, …); subcommands for actions. Use REST on loopback when the daemon is the source of truth; hit the DB directly only for bulk / offline operations.
3. **Update `docs/cli.md`** — the reference agents and humans read. At minimum add a row in the "New-command reference" table in §3; add a recipe in §10 if the command enables a new workflow.
4. **Update the skill** at `.claude/skills/autocaller/SKILL.md` **and** sync to `/root/.openclaw/workspace/skills/autocaller/SKILL.md` (or `cp` between them). The skill is what other AI agents load to know the system. If you added a command the skill doesn't mention, the next agent won't find it.
5. **Update the vision / feature docs** in `docs/` where the change is material — `VISION.md`, `SELF_IMPROVEMENT.md`, `DISPOSITIONS.md`, `FRONTEND.md`, `SIMULATED_RECEIVER.md`, `VOICE_PROVIDERS.md`.

Lead-generation changes have one additional documentation rule:
update the clean lead-gen docs according to their scope:
`docs/CYBERNETIC_LEAD_GEN_CONCEPT.md` for conceptual changes,
`docs/LEAD_GEN_CYBERNETIC_TECHNICAL.md` for implemented code, APIs, schema,
configuration, operations, and tests. Active backlog entries now live in the
DB-backed `todos` table and should be added through the `/todos` UI or
`bin/autocaller todos ...`, not through a markdown todo file. Keep the docs
mostly mutually exclusive: do not bury active todos in the concept doc, and do
not describe aspirational behavior as implemented in the technical doc.

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

- **OpenClaw gateway: always use the `openclaw/proxy` agent, never `openclaw`.**
  Every autocaller LLM call that goes through the OpenClaw gateway
  (`call_skill_json`, the composer, PHI egress guard, lead-feedback
  classifier, blog/outreach composer, listening-prep, etc.) MUST target the
  lightweight **`openclaw/proxy`** agent. The default `openclaw` (main) agent
  loads the `active-memory` extension, which reads a *daily* memory file
  (`~/.openclaw/workspace/memory/<date>.md`); when that day's file is missing
  the tool fails on every turn, which (a) injects `⚠️ 🛠️ … failed` chatter
  into responses, (b) adds ~30s latency, and (c) causes intermittent
  "incomplete turn" failures that fail-close the PHI guard and block sends.
  The proxy agent has no memory extension — it's fast, clean, and stateless,
  which is correct for autocaller's single-shot JSON tasks (they're fully
  specified by SKILL.md + payload and gain nothing from cross-session memory).
  Code defaults are set to `openclaw/proxy`; keep it that way. Env overrides:
  `OPENCLAW_DEFAULT_MODEL`, `LEAD_EMAIL_COMPOSER_MODEL`, `LEAD_FEEDBACK_MODEL`,
  `BLOG_OUTREACH_MODEL`, `OUTREACH_PHI_GUARD_MODEL` — all should be
  `openclaw/proxy` (or another lightweight, memory-less agent), never the bare
  `openclaw`. Direct-OpenAI calls (`gpt-4o-mini` for the judge, lead-extractor,
  IVR navigator) do not use the gateway and are unaffected. When the
  master-agent WIP lands, point `MASTER_AGENT_*_MODEL` at `openclaw/proxy` too.
- **Long response handling.** Any AI-agent response expected to exceed 50 lines
  must replace `/home/pranav/autocaller/long-response.md` with the full answer
  and keep the chat reply short, pointing to that file. Do not append to the
  file for these long responses; replace it so the file always contains the
  latest long answer.
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
