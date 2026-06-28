# PACKET FIRMINTEL E0b — Non-destructive duplicate merge (EmailTag)

Workdir: `/home/pranav/emailtag`. Source: `docs/MIGRATION_PLAN.md` (E0 dedup
intent, deferred from PACKET E0) and `docs/FIRM_INTELLIGENCE_CONTRACT.md` §2
(identity, alias table, "merge not delete"). Read both first. **Depends on E0
(committed):** `firm_alias` table, `canonical_domain()`, `app/services/firm_dedup.py`.

You are Codex, the implementer. **Build the merge tooling. DO NOT execute the
merge against production data.** Dry-run + unit tests only. This runs *before*
E1 so enrichment isn't wasted on duplicates.

## Context (measured, full base)
3,606 records → 1,872 distinct canonical domains; **654 duplicate clusters,
1,102 rows collapse on merge** (~30% are dupes). Some clusters are bad
extractions (`google.com` x7, a `mimecast` row under `bdj.com`); some may be
legit multi-office firms. So merging must be **guarded and reviewable**, never blind.

## Scope (build all)
1. **Merge service** `app/services/firm_merge.py` consuming `firm_dedup`
   clusters (keyed by `canonical_domain`). For each cluster pick a **survivor**
   (most complete: has website > most conversation_ids > has leadership > most
   recently updated) and merge the others into it **non-destructively**:
   - **Union** list data: `emails`, `phones`, `conversation_ids`, `leadership`,
     `contacts`, behavioral/research where present. Keep provenance.
   - For scalar conflicts, keep survivor's value but retain the loser's in a
     `merged_from` provenance blob.
   - Record every merged record's id as a `firm_alias` (`alias_type=legacy_pif_id`,
     `firm_id`=survivor, `source=merge`, confidence).
   - **Soft-merge** losers (e.g. `merged_into=<survivor_id>` + status flag) —
     **never hard-delete a row.**
   - Write a **merge audit record** sufficient to **undo** the merge.
2. **Confidence + guards (auto-merge only when safe):**
   - Auto-merge a cluster only if its canonical domain is a *real firm domain*
     AND member names are similar (token/fuzzy match).
   - **Never auto-merge** on junk/shared domains — maintain an exclusion set
     (`google.com`, `mimecast.com`, generic mail/security vendors) and detect
     "many dissimilar names on one domain" → route the whole cluster to the
     **review queue** instead.
   - No-domain firms (the ~632 with no derivable domain) are **out of scope** —
     they need website resolution first.
3. **Dry-run mode (default)** — produce a report of intended actions
   (survivor, losers, unioned fields, conflicts, review-flagged clusters) with
   **zero DB writes**. Add a Celery task / CLI entry to run dry-run vs apply.
4. **Undo** — a function that reverses a merge from the audit record (restores
   losers, removes the merge aliases).

## Repo conventions
- SQLAlchemy + Alembic migration for any new columns (`merged_into`, status,
  audit table); Celery task pattern; pytest under `test/`.

## Guardrails (hard)
- **DO NOT run the merge against production data.** Build, dry-run on fixtures,
  unit-test only. No live DB mutation.
- **Never hard-delete.** Merge is soft + reversible via alias log + audit record.
- **Do NOT `git commit`/`git push`.** Orchestrator commits and runs the real merge.
- Additive only; no service restarts, no `/etc`, no Docker. `pip` via requirements.txt.

## Validation (run, report output)
- `pytest test/ -k "merge"` — all green.
- Test: high-confidence cluster (e.g. "Yagman & Yagman" variants on `yaglaw.com`)
  → merges, survivor chosen, emails/conversation_ids unioned, losers soft-marked,
  legacy_pif_id aliases recorded.
- Test: junk cluster (`google.com` with dissimilar names) → **NOT merged**, all
  routed to review.
- Test: **undo** restores pre-merge state.
- Dry-run on a fixture set prints a readable plan with no writes.

## Report (end of run)
List files added/changed + migration id, how to run the dry-run + tests, and
STOP. Do not execute against production; do not start E1.
