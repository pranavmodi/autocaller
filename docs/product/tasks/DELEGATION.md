# Listening System — Codex Delegation Runbook

*Orchestrator: Claude (this repo's agent). Implementer: Codex via `codex exec`.
Source plan: `docs/product/LISTENING_SYSTEM_IMPLEMENTATION_PLAN.md`.*

## Division of labor

- **Codex** implements one bounded packet at a time, runs the packet's
  validation commands, and reports. It never restarts services, never
  installs systemd units, never runs the full LLM backfill, never commits in
  autocaller.
- **Claude (orchestrator)** checkpoints git before each run, launches codex,
  reviews the diff against the packet scope, performs live verification,
  handles service restarts (autocaller only after the active-call check),
  installs systemd units, runs the expensive backfills, commits, and flips the
  `listening` todos (#37–41).

## Packet sequence

| # | Packet | Workdir | Depends on |
|---|--------|---------|------------|
| 1 | `PACKET_1_recurrence.md` — timers + backlog script | mission-control | — |
| 2a | `PACKET_2A_corpus.md` — schema, adapters, extractor, backfill script | mission-control | 1 |
| 2b | `PACKET_2B_sources.md` — RSS poller, paste channel, /listening page | mission-control | 2a |
| 3 | `PACKET_3_synthesis.md` — mindset brief, search, digest | mission-control | 2a |
| 4 | `PACKET_4_autocaller.md` — CLI group, composer integration, docs | autocaller | 3 |
| 5 | `PACKET_5_proactive.md` — watchdog, alert rules, proposed sources | mission-control | 2a |

2b, 3, 5 can run in any order after 2a; run them serially anyway — same files.

## Launch

```bash
docs/product/tasks/run_packet.sh docs/product/tasks/PACKET_1_recurrence.md \
  /root/.openclaw/workspace/mission-control
```

The runner pipes the packet to `codex exec` with `-s workspace-write`,
network enabled in-sandbox, `--skip-git-repo-check`, and tees the session log
to `docs/product/tasks/logs/`.

## Orchestrator loop (per packet)

1. **Pre-flight:** `git -C <workdir> add -A && git commit -m "checkpoint: before listening packet N"`
   (MC has unrelated WIP — checkpoint protects it; the repo already uses
   checkpoint commits). For autocaller: ensure clean-enough tree, no checkpoint
   commit of unrelated master-agent WIP — stash review instead.
2. **Launch** the runner (background; logs streamed to file).
3. **Review:** `git diff` against packet scope. Anything outside scope → revert
   that hunk, note for packet revision.
4. **Verify live:** restart `mission-control-backend.service`, run the
   packet's acceptance checks against :8001. For autocaller: check
   `/api/calls/active` + recent `ended_at IS NULL` rows before any restart.
5. **Finalize:** descriptive commit (Co-Authored-By Claude), update todo
   status, install/start any systemd units codex wrote to `deploy/`, run
   deferred expensive steps (Reddit backlog batches, extraction backfill).
6. If validation fails: `codex exec resume --last` with the failure output
   rather than a fresh session.

## Standing guardrails (embedded in every packet)

- New MC backend code lives in `backend/listening.py` (APIRouter), not in the
  8,973-line `main.py`; main.py gets only the `include_router` + import lines.
- Do not modify the uncommitted podcast-SSR WIP in `main.py`/frontend beyond
  those lines.
- No service restarts, no /etc writes, no `pip install` outside
  `requirements.txt` edits + venv install.
- Temp test server on port **18001** only; tag test rows `source='TEST'` and
  delete them before finishing.
- LLM calls in validation: ≤10 items, using MC's existing Anthropic key/config.
