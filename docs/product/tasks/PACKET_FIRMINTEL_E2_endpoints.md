# PACKET FIRMINTEL E2 — v2 contract endpoints (EmailTag, read-only)

Workdir: `/home/pranav/emailtag`. Source: `docs/MIGRATION_PLAN.md` (task E2) and
`docs/FIRM_INTELLIGENCE_CONTRACT.md` §4 (firm_profile), §7 (endpoints), §8
(field mapping). Read all three first. **Depends on E0** (already committed:
`firm_alias`, `canonical_website`, website fields).

You are Codex, the implementer. Implement **E2 only** — the READ-side contract
surface. **Do NOT implement `POST /outcomes`** (that is E4) and do NOT start any
other task.

## Scope (build all)
1. New FastAPI router under `/api/v2/firm-intel` (own module, e.g.
   `app/api/api_v1/endpoints/firm_intel.py` or a v2 path — match repo routing).
   Auth via the existing `PIFSTATS_AUTH_TOKEN` mechanism used by current
   pif-info endpoints.
2. **`firm_profile` serializer** per contract §4 — assemble identity, people,
   relationship (incl. inbox-split recency + neutral `warm_score`), behavior,
   `vendor_stack`, icp, research, and provenance/freshness from existing
   `pif_info` + `firm_alias` + behavioral/front data already present. Where a
   field isn't populated yet (E1 not run), return null/empty with correct shape
   — do not fabricate.
3. Endpoints (read-only):
   - `GET /firms/{firm_id}` → full firm_profile
   - `GET /firms?updated_since=<ts>&cursor=` → delta list (paginated)
   - `GET /firms/resolve?website=|domain=|email=|legacy_pif_id=` → firm_id (via firm_alias + canonical_domain)
   - `GET /firms/{firm_id}/people` → people only
   - `GET /health` → coverage + freshness summary
4. **Non-PHI guarantee:** the serializer must never emit patient names, DOBs,
   medical details, message bodies, or raw conversation content — only derived
   firm intelligence. Add a test asserting known PHI-ish fields are absent.

## Repo conventions
- FastAPI router + Pydantic response schemas; register in the API router.
- pytest under `test/`. Match existing endpoint + schema patterns.

## Guardrails (hard)
- **Read-only. Additive only. Delete nothing.** No writes to pif_info or any
  table from these endpoints.
- **Do NOT `git commit`/`git push`.** Orchestrator commits.
- No live external calls; tests use the test client + fixtures/mocks, not prod data.
- No service restarts, no `/etc`, no Docker. `pip` only via requirements.txt edit.

## Validation (run, report output)
- `pytest test/ -k "firm_intel or firm_profile or resolve"` — all green.
- Round-trip check: a test builds a firm_profile and asserts every field in
  contract §8 mapping is present (null allowed) and **no PHI fields** are emitted.
- `GET /firms/resolve?email=jane@smithlaw.com` resolves via canonical_domain +
  firm_alias in a test.

## Report (end of run)
List files added/changed, the endpoint paths, how to run the tests, and STOP for
human review. Do not implement E4 (`POST /outcomes`).
