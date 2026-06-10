# Packet 4 — Autocaller consumer: CLI group, composer integration, docs

You are the implementer, working in /home/pranav/autocaller (NOT mission
control). Depends on Packet 3 (brief endpoints live on :8001).

## Read first
- CLAUDE.md (golden rule: CLI parity + doc/skill updates are mandatory)
- docs/product/LISTENING_SYSTEM_IMPLEMENTATION_PLAN.md (Phase 4)
- app/services/pifstats_sync.py (pattern: httpx client to mission control)
- app/cli.py (group conventions), docs/cli.md (§3 table, §10 recipes)
- app/services/lead_email_composer_variants.py and where composes record
  prompt_version on email logs (grep `prompt_version` in app/)

## Objective
Make the mindset brief consumable from autocaller: a `listening` CLI group, an
insight-led composer hook, and `brief_version` recorded on email logs.

## Tasks
1. `app/services/listening_client.py` — thin httpx client for
   http://127.0.0.1:8001/api/listening (brief, insights search, stats, digest,
   sources). Graceful "mission control unreachable" errors.
2. CLI group `listening` in app/cli.py:
   - `listening brief [--version N]` — print markdown brief
   - `listening search "<q>" [--type T] [--who W] [--limit N]`
   - `listening quotes --cluster <c> [--limit 5]`
   - `listening sources` — name, kind, last_polled_at, stale flag
   - `listening prep <firm-or-name>` — fetch firm context from local DB
     (patients/firm_contacts by name LIKE) + top matched insights; one LLM call
     via app's existing gateway to render persona / expected objections /
     vocabulary one-pager
3. Composer: in the variant that composes lead-gen emails, fetch latest brief
   version + top-k insights (k=5, matched on firm practice/tags); include as
   prompt context; **record `brief_version` alongside the existing
   prompt-version field on the email log row** (Alembic migration for the new
   nullable column on the email log table). Soft-fail: if MC is down, compose
   proceeds without insights and brief_version stays NULL.
4. Tests: unit tests for listening_client (mock httpx) and the brief_version
   recording path, following existing test conventions.
5. Docs per golden rule: rows in docs/cli.md §3 + a §10 recipe ("morning
   mindset check", "pre-call prep"); update
   .claude/skills/autocaller/SKILL.md AND copy to
   /root/.openclaw/workspace/skills/autocaller/SKILL.md.

## Constraints
- Do NOT commit; do NOT restart the daemon (orchestrator handles both — there
  is a hard rule about restarts during active calls).
- Do NOT touch prompt files / PROMPT_VERSION; insights enter as context, not
  as a prompt-text change. If you find this impossible without editing a
  prompt file, stop and report instead.
- Migration must be additive and nullable only.

## Validation (include output)
- `python -m pytest tests/ -k listening` (your new tests) green; full suite
  not broken (`-q` summary).
- `bin/autocaller listening brief`, `search`, `sources` work live against :8001.
- `listening prep` on one real firm prints a coherent one-pager.
- Show the migration applies + downgrades cleanly on a throwaway check
  (alembic upgrade/downgrade in dry form is fine to describe if env forbids).

## Done when
CLI group works against live MC, brief_version lands on email logs in tests,
docs + both SKILL.md copies updated, nothing committed.
