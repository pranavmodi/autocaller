# CLAUDE.md — project rules for Claude Code (and any AI agent editing this repo)

## Golden rule — CLI parity for every feature

**Every backend capability, setting, or operator action MUST have a CLI command.** The UI is for observability; the CLI is the operator contract. Anything exposed only in the UI or via raw REST becomes invisible to headless agents, cron jobs, shell scripts, CI, and anyone comfortable on a terminal — which includes *us*.

Whenever you add a feature:

1. **Build the backend** — service code, REST endpoint, DB migration, etc.
2. **Add a CLI wrapper** in `app/cli.py` that drives it. Prefer a top-level group for a new domain (`system`, `mock`, `allowlist`, `followups`, …); subcommands for actions. Use REST on loopback when the daemon is the source of truth; hit the DB directly only for bulk / offline operations.
3. **Update `docs/cli.md`** — the reference agents and humans read. At minimum add a row in the "New-command reference" table in §3; add a recipe in §10 if the command enables a new workflow.
4. **Update the skill** at `.claude/skills/possibleos/SKILL.md` **and** sync to `/root/.openclaw/workspace/skills/possibleos/SKILL.md` (or `cp` between them). Keep `.claude/skills/autocaller/SKILL.md` as the legacy alias while older agents still load it. The skill is what other AI agents load to know the system. If you added a command the skill doesn't mention, the next agent won't find it.
5. **Update the vision / feature docs** in `docs/` where the change is material — `VISION.md`, `SELF_IMPROVEMENT.md`, `DISPOSITIONS.md`, `FRONTEND.md`, `SIMULATED_RECEIVER.md`, `VOICE_PROVIDERS.md`.

Lead-generation changes have one additional documentation rule:
update the clean lead-gen docs according to their scope:
`docs/CYBERNETIC_LEAD_GEN_CONCEPT.md` for conceptual changes,
`docs/LEAD_GEN_CYBERNETIC_TECHNICAL.md` for implemented code, APIs, schema,
configuration, operations, and tests. Active backlog entries now live in the
DB-backed `todos` table and should be added through the `/todos` UI or
`bin/possibleos todos ...`, not through a markdown todo file. Keep the docs
mostly mutually exclusive: do not bury active todos in the concept doc, and do
not describe aspirational behavior as implemented in the technical doc.

## Key GTM / strategy docs

- **Freeware wedge GTM (portfolio):** `docs/product/FREEWARE_GTM_STRATEGY.md` —
  umbrella strategy for Possible Minds' free, firm-specific diagnostic tools
  (aiscan = AI Search Visibility, aiaudit = AI Readiness Audit, + future tools).
  Defines the franchise rules every new freeware tool must inherit. Read this
  before building or pitching a new free diagnostic.
- **Founder persona + new-tool backlog:** `docs/product/PI_FOUNDER_PERSONA_AND_FREEWARE_IDEAS.md`
  — research-grounded PI owner persona, ranked pain map, and the ranked backlog of
  next freeware tools (top: Ghost Lead Test, Intake Conversion Teardown).
- **Firm Intelligence Contract (possibleos↔emailtag co-design):**
  `/home/pranav/emailtag/docs/FIRM_INTELLIGENCE_CONTRACT.md` — the versioned
  data-product interface EmailTag publishes and possibleos consumes (website-keyed
  firm identity, layered raw→refined store, the `firm_profile` object, outcome
  feedback loop). Keystone for eliminating possibleos's direct Front dependency.
- **Per-tool spec (aiscan):** `docs/product/AI_SEARCH_VISIBILITY_TOOL_SPEC.md`.
- **Per-tool spec (aiaudit):** `/home/pranav/AIAudit/` (separate repo, README +
  `docs/`).
- **GTM reasoning / channel + ICP:** `docs/product/GTM_STRATEGY_2026-06.md`.
- **Outbound BD vision:** `docs/VISION.md`. **Lead-gen loop:**
  `docs/CYBERNETIC_LEAD_GEN_CONCEPT.md`.

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

- **EmailTag web search is disabled.** Do not build or retain Possible OS
  functionality that depends on EmailTag executing web searches or web
  research. Any such workflow must run locally in Possible OS, normally through
  the loopback OpenClaw gateway, and persist results in the local Possible OS
  database. Audit older start/status relays before relying on them; if they
  still queue EmailTag research, migrate them locally first. EmailTag may remain
  a source for data it already stores through its supported sync APIs, but it is
  not an available web-research backend. Job-opening research is already local.

- **Decision log — record important decisions every session.** Architectural,
  strategic, policy, tooling/transport, flag-flip, deferral, and reversal
  decisions MUST be appended to `docs/decisions/<YYYY-MM-DD>.md` (UTC date), in
  the format in `docs/decisions/README.md`. This is the cross-session,
  cross-agent memory of *why* things are the way they are — every chat window
  working in this repo contributes to it. Rules:
  - **Append-only.** Never rewrite or delete a past decision. To change one, add
    a NEW entry and mark the old one `Status: superseded by <id>`.
  - **Incremental.** Add entries as decisions are made, or at end of session —
    do NOT batch weeks of history into one dump.
  - **Tag every entry with an `area:`** (`lead-gen`, `deliverability`,
    `data-arch`, `website`, `infra`, `process`, `product`) so the log stays
    grep-able by topic — that gives the by-function-area view without storing
    by area (storage is by date, which is append-only and conflict-free across
    parallel windows).
  - **Log decisions, not activity.** A routine bugfix, refactor, or rename is not
    a decision; a choice between approaches, a policy/flag change, a deferral, or
    a reversal is. One line per decision is fine.
- **OpenClaw gateway: use an agent that exists in the live gateway.** The former
  `openclaw/proxy` agent is unavailable and returns `Unknown agent 'proxy'`.
  New local web-research workflows must explicitly use `openclaw/main` unless a
  tested lightweight replacement is introduced. The gateway is loopback-only,
  so these calls execute on the Possible OS server. Before changing an older
  single-shot JSON workflow that still defaults to `openclaw/proxy`, verify its
  live model and migrate it deliberately; do not assume the stale default works.
  Direct-OpenAI calls do not use this gateway and are unaffected.
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

## Delegating implementation to Codex

Bounded implementation work may be delegated to **Codex** (`codex exec`). The
division of labor and full loop are in `docs/product/tasks/DELEGATION.md` — read it
before delegating. The essentials:

- **Roles.** *Claude = orchestrator*: plans, splits work into packets, checkpoints
  git, launches Codex, reviews the diff against packet scope, does live
  verification, restarts services, commits, updates the decision log + todos.
  *Codex = implementer*: builds **one bounded packet at a time**, runs the packet's
  validation commands, and reports. Codex **never** commits/pushes, restarts
  services, writes to `/etc`, installs systemd units, or runs expensive backfills —
  those are the orchestrator's job.
- **A packet** is a self-contained markdown file under `docs/product/tasks/`
  (e.g. `PACKET_*.md`) with: **Workdir + Source**, **Scope** (exactly what to build,
  what NOT to), **Repo conventions**, **hard Guardrails** (additive-only, no
  commit/push, no restarts, list any WIP/legacy files that must stay untouched), and
  **Validation** (the exact commands Codex must run and report). Keep it bounded and
  additive.
- **Launch** with the runner (pipes the packet to `codex exec -s workspace-write`,
  network enabled in-sandbox, `-C <workdir>`, teed to `docs/product/tasks/logs/`):
  ```bash
  docs/product/tasks/run_packet.sh docs/product/tasks/PACKET_X.md <workdir>
  ```
  `<workdir>` may be another repo (e.g. `/home/pranav/emailtag`) — packets are
  cross-repo.
- **Orchestrator loop per packet:** pre-flight git checkpoint (protect unrelated
  WIP — do NOT checkpoint-commit someone else's in-flight work; snapshot/stash and
  review instead) → launch → review `git diff` vs scope (revert out-of-scope hunks)
  → verify live (build/tsc/tests + service check; for autocaller check
  `/api/calls/active` before any restart) → finalize (descriptive commit
  Co-Authored-By Claude, decision-log entry, todos) → on failure
  `codex exec resume --last` with the failure output rather than a fresh session.
