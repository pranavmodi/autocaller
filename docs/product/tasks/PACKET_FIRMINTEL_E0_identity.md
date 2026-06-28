# PACKET FIRMINTEL E0 — Canonical identity + tiered website resolution (EmailTag)

Workdir: `/home/pranav/emailtag`. Source plan: `docs/MIGRATION_PLAN.md` (task E0)
and `docs/FIRM_INTELLIGENCE_CONTRACT.md` §2 (Identity model + "Website
resolution (tiered)"). Both are in the emailtag repo — read them first.

You are Codex, the implementer. Implement **E0 only**. Do not start E1+.

## Scope (build all four)

1. **`canonical_domain(value)` helper** — strip scheme/`www`/path/query; reduce
   to registrable domain (eTLD+1) via a public-suffix library (add to
   `requirements.txt`). Return **no key** for: vanity/portal domains
   (`*.filevineapp.com`, `*.casepeer.com`, `*.litify.com`, smartadvocate) and
   consumer domains (gmail/yahoo/outlook/hotmail/icloud/aol).

2. **`firm_alias` table + Alembic migration** — columns: `alias_type`,
   `alias_value`, `firm_id` (FK→pif_info.id), `confidence`, `source`,
   `created_at`. `alias_type ∈ {legacy_pif_id, domain, alt_domain, email_domain,
   vanity_domain, firm_name_fuzzy}`. Add minimal CRUD.

3. **Tiered website resolver** (contract §2 "Website resolution (tiered)"):
   seed from `firm_website` else email domain → HTTP-verify it is the firm's
   real site → `web_search_preview` fallback (REUSE `pifstats/src/firm_researcher`)
   → human-review-queue stub. Persist on `pif_info` (add columns via migration if
   missing): `canonical_website`, `website_status` (resolved|pending|none),
   `website_source` (email_verified|web_search|human), `website_confidence`.

4. **Dedup clustering routine** — group firms by `canonical_domain`, FLAG
   clusters (>1 firm) for review. **Do NOT auto-merge** in this packet.

## Repo conventions
- Celery task for the resolver (see `app/tasks/`); Alembic migration under
  `migrations/`; pytest tests under `test/`. Match existing patterns.

## Guardrails (hard)
- **Additive only. Delete nothing** — no dropped tables/columns/code.
- **Do NOT execute any production backfill.** Do NOT call live `web_search` or
  live HTTP against real firms. Unit-test the resolver with **mocked** HTTP +
  search only.
- **Do NOT `git commit` or `git push`.** The orchestrator reviews and commits.
- No service restarts, no `/etc` writes, no Docker actions.
- `pip install` only via `requirements.txt` edit (note it; orchestrator installs).

## Validation (run these, report output)
- `python -c "from <module> import canonical_domain; print(canonical_domain('https://www.SmithLaw.com/x'), canonical_domain('a@smithlaw.filevineapp.com'), canonical_domain('b@gmail.com'))"`
  → expect `smithlaw.com`, no-key, no-key.
- `alembic upgrade head` against a **scratch/test** DB only (not production).
- `pytest test/ -k "identity or website or alias or canonical"` — all green.

## Report (end of run)
List files changed/added, the new migration revision id, how to run the tests,
and STOP for human review. Do not proceed to E1.
