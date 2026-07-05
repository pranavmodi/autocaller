# PACKET FIRMINTEL E5 — contract deltas for LexVisibility (EmailTag)

Workdir: `/home/pranav/emailtag`. Source: `docs/FIRM_INTELLIGENCE_CONTRACT.md`
and the v2 router `app/api/api_v2/endpoints/firm_intel.py`.

You are Codex. Build only what this packet scopes. Do NOT commit, push, restart
services, run Docker, or touch the production DB. Unit tests only (existing
`test/` fixture patterns — see `test/test_firm_events.py`,
`test/test_firm_intel.py`).

## Why

LexVisibility (a new consumer of the v2 firm-intel contract) needs two small
additions: (1) when its AI-answer scans discover law firms that don't resolve
to any known firm, it must be able to create **candidate firm records** so
identity stays owned by EmailTag; (2) its report-engagement moments
(`report_viewed`, `report_engaged`) must be accepted by the existing external
signal endpoint so they land in the firm event stream.

## Scope (build all)

### 1. Candidate firm creation — `POST /api/v2/firm-intel/firms`

Add to the v2 router (token auth comes free from the router dependency):

- Request schema `CandidateFirmIn`: `firm_name` (required, 1–512 chars),
  `website` (optional), `domain` (optional), `email` (optional),
  `metro`/`city`/`state` (optional strings), `source` (required; same
  normalization rules as `ExternalFirmSignalIn.vendor` — lowercase, no `:`),
  `detail` (dict, default {}).
- Behavior (idempotent-by-identity):
  1. Derive a canonical domain from website/domain/email via the existing
     `canonical_domain()` in `app/services/firm_identity.py` (skip
     vendor/consumer domains per its rules).
  2. If a canonical domain exists, resolve it against `firm_alias` and
     `pif_info.canonical_website` (reuse the same lookup the
     `GET /firms/resolve` endpoint uses — factor a shared helper if needed,
     do not copy-paste).
  3. **Match found** → return 200 `{firm_id, created: false, matched_by: ...}`.
  4. **No match** → create a `PifInfo` row (entity_type `pi_law_firm`,
     defaults for the non-null array/JSONB columns, `canonical_website` set
     when derivable, `extraction_notes` = f"candidate created via {source}"),
     plus `firm_alias` rows for the domain(s). Return 201
     `{firm_id, created: true}`.
  5. No canonical domain at all (name only) → still create, but fuzzy-check
     first: exact case-insensitive `firm_name` match among active firms →
     treat as matched. (Keep it to exact-normalized name match; no
     fuzzy-scoring in this packet.)
- Response schema `CandidateFirmResponse`: `firm_id`, `created`, `matched_by`
  (`domain|alias|name|none`), `canonical_website`.
- Firms created this way must appear in the delta feed (they will, via
  `updated_at`) and must be excluded from nothing — they are ordinary firms
  with sparse data.

### 2. Two new event types

- Extend `FirmEventType` in `app/schemas/firm_event.py` with `report_viewed`
  and `report_engaged`.
- Alembic migration (single head on top of the current head — run
  `alembic heads` first and chain correctly): ALTER the
  `ck_firm_event_type` check constraint on `firm_event` to include the two new
  values (drop + recreate constraint; no data changes).
- The catalog endpoint (`GET /events/catalog`) must reflect them (it derives
  from the Literal — verify, don't assume).
- `POST /events/external` must accept them end-to-end (signal_type is already
  typed as `FirmEventType`; confirm no other allowlist blocks them — e.g.
  `detect_engagement_event`'s `{link_opened, link_clicked}` set is for the
  internal engagement source and must NOT gate external signals).

### 3. Publish the full research + people detail in the v2 profile

The v2 `firm_profile` currently omits fields consumers need for replication
and personalization. Extend the serializer (`build_firm_profile` in
`app/services/firm_intel.py`) and the schemas in `app/schemas/firm_intel.py`
— **additively, no renames**:

- `research`: add `founded_year`, `firm_size`, `office_locations` (list),
  `notable_cases` (list), `awards_recognition` (list), `bar_associations`
  (list), `social_media` (dict) — passed through from `pif_info.research_data`
  when present, null/empty otherwise.
- `people[]`: add optional `linkedin`, `bio`, `publications` (list),
  `cases_handled` (list), `bar_admissions` (list) — passed through from the
  leadership/staff records when present.
- `identity`: populate `metro`/`city`/`state` from research_data office
  locations when the dedicated fields are absent (first office wins; do not
  geocode — string passthrough only).
- Update the profile fixture assertions in `test/test_firm_intel.py`
  accordingly; new fields must be optional so old records still serialize.

### 4. Contract doc update

`docs/FIRM_INTELLIGENCE_CONTRACT.md`:
- Update the status header: v2 endpoints implemented + deployed (2026-07-05),
  token auth live.
- Add `POST /firms` (candidate creation) to the §7 endpoint table.
- Add `report_viewed`/`report_engaged` to the §5 event vocabulary with a note
  that they arrive via `POST /events/external` from `external:lexvisibility`.
- Document the §4 profile additions (research detail + people detail fields).

## Repo conventions

Async SQLAlchemy; FastAPI; pydantic v2 schemas in `app/schemas/`; CRUD helpers
in `app/crud/`; tests in `test/` using the existing async fixture patterns;
alembic in `migrations/versions/` (maintain a single head).

## Guardrails (hard)

- **Additive only.** No changes to existing endpoints' behavior or response
  shapes; no deletion; no renames.
- **Do NOT `git commit`/`git push`; no service restarts; no Docker; no /etc.**
- Do not modify `app/api/api_v1/**` (the cookie-auth v1 surface) at all.
- Do not run alembic against any live DB — write the migration file only;
  validate it with `alembic upgrade head --sql` (offline SQL emit) if runnable,
  otherwise by review.
- No live HTTP/LLM calls in tests.

## Validation (run, report)

- `pytest test/ -k "candidate or firm_event or firm_intel" -q` — all green.
  Must cover:
  - create-new: POST /firms with unknown domain → 201, pif_info row + alias
    rows exist;
  - idempotent: same POST again → 200, same firm_id, created=false;
  - match via alias and via canonical_website;
  - name-only create + name-only exact match;
  - vendor/consumer domain input (e.g. smithlaw.filevineapp.com, gmail.com)
    → not used as identity (name-only path);
  - POST /events/external with signal_type=report_viewed → 201 and the event
    row has the type; catalog lists both new types.
  - profile serialization: a fixture firm with rich research_data/leadership
    emits the new research fields (office_locations, notable_cases, awards…)
    and people fields (linkedin, publications…); a sparse firm still
    serializes with them null/empty.
- `alembic heads` shows exactly one head after your migration.
- Confirm `pytest test/test_firm_events.py test/test_firm_outcomes.py -q`
  still green (no regressions).

## Report (end of run)

Files added/changed + migration id, the resolve-order you implemented
(domain → alias → name), test results, and STOP.
