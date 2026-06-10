# Packet 2A — Unified corpus: schema, adapters, extractor, backfill script

You are the implementer. Orchestrator reviews, restarts services, runs the
full backfill. Stay in scope.

## Read first
- /home/pranav/autocaller/docs/product/LISTENING_SYSTEM_IMPLEMENTATION_PLAN.md (Phase 2, incl. full DDL)
- /home/pranav/autocaller/docs/product/LISTENING_SYSTEM_DESIGN.md (§3 extraction taxonomy)
- backend/main.py: aiosqlite usage + init_db pattern, the Anthropic call
  pattern used by `reddit_analyze_post` (~3680) and `do_analyze_posts` (~1954),
  BackgroundTasks pattern (`do_transcribe` ~1311)
- /home/pranav/autocaller/.claude/skills/yelp-review-quotes/SKILL.md — model
  for verbatim-quote-first extraction prompts

## Objective
Create the unified listening corpus: 4 new tables, adapters that copy existing
content in, an LLM insight extractor, and a backfill script — all in a new
`backend/listening.py` APIRouter module.

## Tasks
1. `backend/listening.py` — APIRouter under `/api/listening`; main.py changes
   limited to import + `app.include_router(...)` + calling listening's
   `init_listening_tables()` from startup.
2. Tables exactly per the plan's DDL: `listening_sources`, `listening_items`
   (UNIQUE content_hash, `is_primary`, `external_ref`), `listening_insights`,
   `mindset_briefs`. Idempotent CREATE IF NOT EXISTS.
3. Seed `listening_sources` (idempotent, keyed on name): the 5 Substack/RSS
   feeds, 5 podcasts (kind=podcast, pointer), 6 subreddits (kind=reddit,
   pointer), PILMMA blog (kind=blog), 10 linkedin person rows (enabled,
   paste-fed) — names per plan §2.3 seed list.
4. `POST /api/listening/sync-adapters` (BackgroundTasks): copy NEW rows into
   `listening_items` via `external_ref` dedup from: `reddit_posts`
   (title+selftext+comments_text), `research_posts` (body),
   `pi_podcast_episodes` status='done' (formatted_transcript, chunk ~24k chars
   with `:chunkN` ref suffix), `job_listings`, `transcriptions` +
   `customer_calls` (is_primary=1).
5. `POST /api/listening/extract` (BackgroundTasks, `{"limit": N}`): for
   status='new' items, one Anthropic structured-output call each (reuse main.py's
   client/key pattern; cheap/haiku-class model id consistent with what main.py
   uses for bulk analysis). Output: insights typed
   pain_point|objection|vocabulary|belief|metric_they_trust|adoption_story|vendor_sentiment,
   verbatim `quote` mandatory, `who_feels_it`, `severity`, `confidence`.
   Insert; mark item extracted/error. Skip items <200 chars (mark skipped).
6. `GET /api/listening/items?status=&source=&limit=`,
   `GET /api/listening/insights?type=&cluster=&who=&q=&limit=` (q = LIKE over
   quote/paraphrase), `GET /api/listening/stats` (counts by status/type/source).
7. `deploy/listening/bin/backfill.sh` — sync-adapters, then loop extract in
   batches of 50 while stats show status='new'>0. Write; run ≤10 items only.

## Constraints
- No service restarts. Test on a temp uvicorn at port 18001 against the live
  DB; tag any rows you fabricate with source name 'TEST' and delete them.
- ≤10 LLM extraction calls during validation.
- No new deps except (if you choose) none — stdlib hashing; httpx already present.

## Validation (include output)
- `python -m py_compile backend/listening.py`
- Temp server: tables exist, seeds inserted, idempotent on second startup.
- sync-adapters on a 20-row slice → items appear with correct external_ref +
  hash dedup proven (run twice, count stable).
- extract limit=5 → ≥1 insight per successful item, all with non-empty
  verbatim quotes present in the source text (spot-check 3).
- stats endpoint reflects the above. TEST rows cleaned.

## Done when
Router live on temp server, adapters + extractor proven on small batches,
backfill.sh ready for orchestrator.
