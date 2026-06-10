# Packet 2B — New sources: RSS/Substack poller, paste channel, /listening page

You are the implementer. Orchestrator reviews, restarts, schedules. Depends on
Packet 2A (backend/listening.py exists).

## Read first
- /home/pranav/autocaller/docs/product/LISTENING_SYSTEM_IMPLEMENTATION_PLAN.md (§2.2)
- backend/listening.py (from Packet 2A)
- main.py `do_crawl` (~1819) for the httpx+bs4 boilerplate-stripping pattern;
  `paste_transcript` (~1593) for the paste pattern
- Frontend: src/app/ routing conventions, src/components/Sidebar.tsx, an
  existing simple page (e.g. goals) for fetch/style conventions

## Objective
Two new ingest channels into `listening_items`, and a minimal `/listening`
page.

## Tasks
1. Add `feedparser` to backend/requirements.txt and install into MC's venv.
2. `POST /api/listening/poll` (BackgroundTasks): for each enabled
   kind∈(rss, blog) source with a feed URL — fetch feed, for entries newer than
   `last_polled_at` fetch full text (httpx+bs4 strip), insert items (hash
   dedup), update `last_polled_at`. Per-source try/except; record errors on the
   source row (add an `last_error` column if needed).
3. `POST /api/listening/paste` `{source_kind, author, url?, title?, text,
   is_primary?}` → upsert a paste/linkedin source for the author, insert item,
   trigger extraction for just that item, return extracted insights inline.
4. Frontend `/listening` page + Sidebar entry: stats header (from
   /api/listening/stats), paste form (author, kind, text → shows returned
   insights), items table (status filter), insights table (type filter, quote,
   author, link). Existing stack only (Tailwind/Lucide), no new deps.
5. Backfill the real feed URLs onto the seeded rss sources where the plan
   names them (LawDroid Manifesto, Adam's Legal Newsletter, Daniel Roche,
   Legal Tech Trends, Rankings.io — Substacks use `<base>/feed`; verify each
   URL resolves, else mark source disabled with last_error).

## Constraints
- No restarts; temp uvicorn on 18001 for backend tests; frontend verified via
  `npm run build` (do not touch the running :3001 service).
- Don't modify the uncommitted podcast WIP files beyond what 2A allowed.
- ≤10 LLM calls (paste-extraction tests).

## Validation (include output)
- poll against ≥2 real feeds → items inserted, second run inserts 0.
- paste a real LinkedIn-style text → item + ≥1 insight returned inline.
- `npm run build` succeeds; screenshot or DOM-dump the page if feasible.
- TEST rows cleaned.

## Done when
Poller + paste land items end-to-end on the temp server; page builds; feed
URLs verified.
