# PACKET LEXVIS L1 — stage-machine pipeline backend + CLI (new repo)

Workdir: `/home/pranav/lexvisibility` (fresh git repo; you build the first
code in it). Source docs: `docs/PILOT_ONE_PLAN.md` and `docs/HANDOFF.md` +
`docs/lexvisibility-2-spec_updated.md` (§2.0 execution modes, §2.4–2.6, §4
orchestration model) — read all three first.

You are Codex. Build the backend only (frontend is packet L2). Do NOT commit,
push, restart services, make network calls at runtime in tests, or call any
LLM. Every stage below is a deterministic transform of already-captured data.

## Why

LexVisibility's core product mechanic is the **step-through pipeline**: every
stage consumes the previous artifact, writes a versioned + SHA-256-hashed
artifact of its own, then HALTS until an operator inspects it and explicitly
advances. The pilot (one firm: Block LLP) already has its scan data captured
in the aiscan tool's SQLite DB; this packet builds the pipeline that turns it
into an examinable chain ending in a report payload.

## Stack (match sibling repos, e.g. /home/pranav/ai-visibility)

FastAPI + aiosqlite (DB at `data/lexvis.db`, gitignored), Click CLI at
`bin/lexvis`, pytest. Python 3.12. `requirements.txt`. No ORM required —
plain SQL like ai-visibility is fine.

## Data model (per spec §4, trimmed for pilot)

- `runs(id TEXT pk, firm_ref TEXT, firm_name TEXT, mode TEXT default 'step',
  current_stage TEXT, status TEXT check in
  ('pending','running','awaiting_review','failed','done'), created_at, updated_at)`
- `stage_artifacts(id TEXT pk, run_id, stage TEXT, version INT,
  status TEXT check in ('draft','current','stale','superseded'),
  payload_json TEXT, content_hash TEXT /* sha256 of payload_json */,
  produced_by TEXT /* 'machine'|'human' */, created_at)`
  — unique (run_id, stage, version). Re-running a stage bumps version and
  marks downstream artifacts `stale`.
- `overrides(id, artifact_id, field_path TEXT, machine_value TEXT,
  human_value TEXT, actor TEXT, created_at)`
- `run_events(id, run_id, event TEXT, stage TEXT, actor TEXT, detail_json,
  created_at)` — audit: every create/advance/rerun/override logged.

## Stage chain (fixed order; each pauses at awaiting_review)

1. **ingest** — copy raw scan data from the aiscan SQLite DB (path via env
   `AIVIS_DB_PATH`, default `/home/pranav/ai-visibility/data/aivis.db`; scan
   id via run creation parameter). Read the scan row, its query rows, raw
   answer texts, and observation JSON. Artifact payload: `{scan_id, market,
   engine: "openai_web_search", queries: [{query_id, category, weight, text,
   runs: [{answer_text, cited_urls, observation_json}]}]}`. This is the
   evidence-of-record; hash it. READ-ONLY access to the aivis DB — never
   write to it. Discover the actual aivis schema by reading
   /home/pranav/ai-visibility/app (db/schema modules) — do not guess table
   names.
2. **extract** — deterministic normalization: per query-run, emit
   `mentions: [{name, rank_position, low_confidence}]` from the stored
   observation competitor data + `target_present` per run. No LLM.
3. **resolve** — map mention names to firm identities against the possibleos
   mirror: read-only SELECTs against Postgres (env `POSSIBLEOS_DB_URL`,
   default `postgresql://localhost/autocaller`) on tables
   `firm_intel_aliases(alias_value, firm_id)` and
   `pif_directory_firms(id, firm_name, canonical_website)`. Match order:
   exact alias_value on normalized domain (when the observation carries a
   domain), else case-insensitive exact firm_name, else fuzzy prefix; below
   threshold → `unresolved: true` (these become candidate-creation work at
   send time, NOT in this packet). Artifact: resolution table with
   match_method + confidence per mention.
4. **score** — visibility computation per spec §2.4: answered-denominator
   headline (`appeared_in X of N answering searches`), per-competitor
   appearance counts/best positions, leaderboard sorted by weighted
   appearances. Deterministic.
5. **dollarize** — carry the assumption trail: artifact embeds the imported
   estimate JSON from the aiscan scan (cases, dollars, assumption_trail) as
   `basis: "aiscan_estimate_v1"`, plus `avg_case_fee` input (run parameter,
   default 15000) and a `[low, high]` monthly range derived as ±35% around
   the base dollars. Every number must trace to an input in the payload.
6. **render** — assemble the report payload per spec §2.6 order: verdict
   line, hero evidence slot (`hero_screenshot: null` placeholder + hero_query
   text + copy-button text), the query×runs grid with per-cell
   present/absent, leaderboard, money section (worksheet from stage 5),
   mechanism section (env-free static copy citing the website gaps passed in
   as run parameter or omitted), dated trend note, CTA block (reply-prompt
   variant). Also mint `report_token` (secrets.token_urlsafe(16)) stored on
   the run.
7. **qa** — no transform; artifact is `{checklist: {...}, approved: bool}`;
   `lexvis qa <run> --approve` sets approved and completes the run
   (status='done').

## API + CLI (CLI parity for everything)

FastAPI app `app/main.py` (port env `LEXVIS_PORT`, default 8140):
- `POST /api/runs` {aivis_scan_id, firm_name, firm_ref, avg_case_fee} →
  creates run, executes stage 1, halts awaiting_review
- `POST /api/runs/{id}/advance` → executes next stage, halts (or completes)
- `POST /api/runs/{id}/rerun/{stage}` → re-execute one stage in isolation,
  bump version, mark downstream stale
- `POST /api/runs/{id}/override` {stage, field_path, value, actor} → record
  override + regenerate artifact with human value, produced_by='human'
- `GET /api/runs`, `GET /api/runs/{id}` (rail view: stages + statuses),
  `GET /api/runs/{id}/artifacts/{stage}` (full payload + hash + versions)
- `GET /api/report/{token}` → the rendered report payload (only when qa
  approved; 403 `{"detail":"pending_qa"}` before that)
- CLI `bin/lexvis`: `initdb`, `run create --scan <aivis_scan_id> --firm-name
  --firm-ref [--avg-case-fee]`, `run list`, `run show <id>`, `advance <id>`,
  `rerun <id> <stage>`, `artifact <id> <stage> [--version N]`,
  `override <id> <stage> <field_path> <value>`, `qa <id> [--approve]`,
  `report-url <id>` (uses env `PUBLIC_BASE_URL`, default
  http://localhost:3140).

## Guardrails (hard)

- No LLM calls, no HTTP calls at runtime except none-needed (all inputs are
  local DBs). Tests use fixture SQLite/postgres-free fakes — do NOT require a
  live Postgres in tests (inject the resolver's lookup function).
- aivis DB strictly read-only; open with `mode=ro` URI.
- Do NOT `git commit`/`git push`. No service restarts, no /etc, no Docker.
- Artifacts immutable once written: re-runs create new versions; never UPDATE
  a payload in place.

## Validation (run, report)

- `pytest tests/ -q` green, covering: full happy-path advance through all 7
  stages with a fixture aivis DB (build a tiny fixture .db in tests); hash
  stability; rerun bumps version + marks downstream stale; override recorded
  and reflected; report endpoint 403 before qa approve, 200 after; audit
  events written for every transition.
- `bin/lexvis initdb && bin/lexvis run create --scan FIXTURE ...` works
  against the fixture DB end-to-end in a temp DB_PATH.
- `python3 -c "import app.main"` clean.

## Report (end of run)

Files created, schema summary, the exact CLI sequence to drive the real
Block LLP scan (aivis scan id 92405031ac5f4011816009287614e3c8) through all
stages, test results, and STOP.
