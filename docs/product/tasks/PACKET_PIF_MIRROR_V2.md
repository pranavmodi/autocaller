# PACKET PIF MIRROR V2 — repoint the firm mirror at the v2 firm-intel contract (possibleos)

Workdir: `/home/pranav/possibleos`. Source docs:
`/home/pranav/emailtag/docs/FIRM_INTELLIGENCE_CONTRACT.md` (§4 firm_profile, §7
endpoints) and `app/services/pif_directory.py` (the current v1 mirror).

You are Codex. Build only what this packet scopes. Do NOT commit, push, restart
services, or call the live API in tests (mock all HTTP).

## Why (context you must know)

possibleos mirrors emailtag's firm directory into Postgres
(`pif_directory_firms`, model `PifFirmRow` in `app/db/models.py`) via
`app/services/pif_directory.py`, which paginates the **v1** API
(`/api/v1/pif-info`). As of 2026-07-05 the deployed emailtag requires
**cookie auth on all v1 routes** — header tokens return 401 — so the existing
sync loop is silently broken. The replacement is the **v2 contract API**:

- Base: `https://emailprocessing.mediflow360.com/api/v2/firm-intel`
- Auth: header `X-PIFStats-Auth-Token: <token>`; token is already in `.env` as
  `PIFSTATS_AUTH_TOKEN` (verified working 2026-07-05).
- `GET /firms?updated_since=<iso>&cursor=<c>&limit=100` → `{items: [firm_profile], next_cursor, total}`
  (delta sync; omit `updated_since` for a full crawl).
- `GET /firms/{firm_id}` → one `firm_profile`.
- `GET /firms/resolve?website=|domain=|email=|legacy_pif_id=` → `{firm_id, ...}`.
- `GET /health` → coverage/freshness summary.
- `firm_profile` shape: see contract §4 — `firm_id`, `canonical_website`,
  `website_status`, `firm_name`, `aliases{legacy_pif_ids,domains,vanity_domains}`,
  `identity{metro,city,state,size_hint,icp_tier,...}`, `people[]` (name, title,
  email, phone, persona, is_decision_maker, confidence), `relationship`
  (warm_score_neutral, total_email_count, last_seen_at, monthly_email_volume,
  inbox_breakdown), `behavior` (primary_pain_point, topic_distribution,
  sender_roles, after_hours_ratio), `vendor_stack`, `icp{score,tier,score_breakdown}`,
  `research{practice_areas,sources,research_status,last_researched_at}`,
  `provenance{refined_at,...}`.

## Scope (build all)

### 1. v2 sync service — `app/services/firm_intel_sync.py` (new module)

- httpx AsyncClient; base URL env `FIRM_INTEL_BASE_URL` (default above), auth
  header `X-PIFStats-Auth-Token` from `PIFSTATS_AUTH_TOKEN`.
- `sync_firm_intel(full: bool = False, limit: int | None = None)`:
  - watermark from a new single-row state table `firm_intel_sync_state`
    (id=1, last_updated_since, last_synced_at, last_result JSONB);
  - `full=True` ignores the watermark;
  - paginate via `next_cursor`; upsert each profile into `pif_directory_firms`
    (mapping below) and its aliases into the new alias table;
  - advance the watermark to the max `provenance.refined_at`/profile
    `updated_at` seen only after a fully successful run;
  - `limit` caps total firms processed (for smoke runs);
  - returns a summary dict like `sync_pif_directory` does.
- Mapping v2 `firm_profile` → existing `PifFirmRow` (do not drop v1 columns;
  only overwrite what v2 provides):
  - `id=firm_id`, `firm_name`, `website=canonical_website` (fall back to first
    `aliases.domains` entry), `icp_score/icp_tier` from `icp`,
    `score_breakdown` from `icp.score_breakdown`,
    `research_status/last_researched_at` from `research`,
    `leadership` = people with `is_decision_maker=true`, `staff` = the rest,
    `emails` = distinct people emails, `phones` = distinct people phones,
    `behavioral_data` = merged `behavior` + `relationship`,
    `research_data` = `research` + `identity` fields,
    `raw_json` = the full v2 profile, `source_updated_at` from provenance.
- New columns on `PifFirmRow` (additive): `canonical_website` (indexed),
  `metro`, `warm_score` (float), `vendor_stack` (JSONB), `profile_source`
  (String(8): 'v1'|'v2'). Set `profile_source='v2'` on v2 upserts.
- New table `firm_intel_aliases` (model `FirmAliasRow`): alias_type,
  alias_value (indexed, lowercased), firm_id, synced_at; unique on
  (alias_type, alias_value). Populate from `aliases` + `canonical_website` +
  people email domains (reuse `normalize_domain` / `is_consumer_domain` from
  `front_sync.py` — import, do not duplicate).
- `resolve_firm_local(value: str) -> str | None`: normalize input (domain,
  email, or URL) and look up `firm_intel_aliases` then
  `pif_directory_firms.canonical_website`/`website`. Pure-local; no HTTP.
- `firm_intel_status()`: totals, `profile_source` counts, watermark, alias
  count, last sync summary, plus a passthrough of remote `GET /health`
  (HTTP allowed here at runtime, mocked in tests).
- Table creation: follow the `ensure_pif_tables()` checkfirst pattern used by
  pif_directory (this repo manages these mirror tables that way, not alembic).

### 2. Wire the daemon loop

In `pif_directory_sync_loop` (pif_directory.py): when the native flag is on,
call `sync_firm_intel()` INSTEAD of the broken v1 `sync_pif_directory()`; keep
the follow-on `ingest_pif_directory_contacts()` call. Leave
`sync_pif_directory` itself in place (mark deprecated in its docstring, log a
warning that v1 requires cookie auth) — do not delete it.

### 3. CLI (golden rule — CLI parity)

Extend the existing `pif` typer group in `app/cli.py`:
- `pif sync [--full] [--limit N]` → repoint to `sync_firm_intel`, print summary.
- `pif status` → extend with the new `firm_intel_status()` fields.
- `pif resolve <value>` → `resolve_firm_local`, fall back to remote
  `/firms/resolve` when not found locally; print firm_id + firm_name.
- `pif show <firm_id|domain>` → print the mirrored profile summary (name,
  website, metro, tier, warm_score, decision-makers w/ emails, vendor_stack).

### 4. Docs

- `docs/cli.md`: update §3 new-command reference rows for the four `pif`
  commands; add a §10 recipe "resync the firm mirror from the v2 contract".
- `.claude/skills/possibleos/SKILL.md`: update the pif section to describe the
  v2 mirror + commands. (Orchestrator will sync the openclaw copy.)
- Do NOT edit CYBERNETIC docs or VISION.md in this packet.

## Repo conventions

Async SQLAlchemy via `AsyncSessionLocal`; typer CLI; httpx; pytest with
`pytest.ini` config; tests under `tests/` named `test_firm_intel_sync.py`.
Mirror-table DDL via checkfirst create (see `ensure_pif_tables`), not alembic.

## Guardrails (hard)

- **No live HTTP in tests** — mock httpx (respx or monkeypatch, follow existing
  test patterns in `tests/`).
- **Additive only**: no dropping columns/tables; do not delete or rewrite
  `sync_pif_directory`, `front_sync.py`, or any lead_gen module beyond the one
  loop hook in §2.
- **Do NOT `git commit`/`git push`; no service restarts; no `/etc`; no Docker.**
- Do not print or hardcode the real `PIFSTATS_AUTH_TOKEN` anywhere (read env).
- Do not touch `.env`.

## Validation (run, report)

- `pytest tests/test_firm_intel_sync.py -q` — all green. Must cover:
  - delta sync: two pages via `next_cursor`, upsert + watermark advance
    (mocked responses with 3 fixture profiles);
  - full sync ignores watermark;
  - mapping: fixture profile → PifFirmRow fields incl. leadership/staff split,
    emails, canonical_website fallback, profile_source='v2';
  - alias upsert idempotent (re-run does not duplicate);
  - `resolve_firm_local` hits by domain, email, legacy_pif_id;
  - watermark NOT advanced when a page raises (failure mid-run).
- `pytest tests/ -q -x -k "pif or firm_intel"` — no regressions.
- `python -c "from app.services.firm_intel_sync import sync_firm_intel"` clean import.
- Do NOT run a live sync — orchestrator does that.

## Report (end of run)

Files added/changed, the field-mapping table you implemented, how to run the
smoke sync (`pif sync --limit 20`), test results, and STOP.
