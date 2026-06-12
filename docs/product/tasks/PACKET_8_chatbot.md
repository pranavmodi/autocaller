# Packet 8 — /listening corpus chatbot (bottom-right popup, search + cite)

You are the implementer in /root/.openclaw/workspace/mission-control. Goal: a
chat assistant on /listening that answers questions about PI-firm leadership
and operations by SEARCHING THE LISTENING CORPUS and CITING its sources — not
from the model's general knowledge.

## Read first
- backend/listening.py: insights/items schema, gateway LLM helpers
  (get_gateway_llm, model "openclaw"), brief storage, exec endpoint
- frontend/src/app/listening/page.tsx: CollapsibleSection, exec card,
  drill-down wiring (?section=insights&cluster=...), MarkdownView component

## Backend

1. **FTS index** (idempotent, in init): SQLite FTS5 virtual table
   `listening_insights_fts(quote, paraphrase, cluster)` content-synced to
   listening_insights (triggers or rebuild-on-init), and
   `listening_items_fts(title, raw_text)` over items. If FTS5 is unavailable,
   fall back to LIKE search transparently.
2. **`POST /api/listening/chat`** `{messages: [{role, content}...]}` →
   `{answer_md, citations: [{n, insight_id?, item_id?, quote, author,
   source_name, url, published_at, cluster}], retrieval: {query_terms,
   filters}}`. Pipeline:
   a. **Retrieval plan**: one cheap LLM call (gateway model "openclaw") that
      converts the user question + chat history into JSON: search terms,
      optional filters (insight type, who_feels_it, cluster, since-date).
      On parse failure fall back to using the raw question as the FTS query.
   b. **Retrieve**: top ~24 insights via FTS ranked by (is_primary of parent
      item DESC, recency of published_at, FTS rank), applying filters; plus
      the latest brief's relevant sections (string-match section headers
      against query terms); plus top 3 matching items' title+snippet for
      context. Dates and authors included.
   c. **Answer**: one LLM call (gateway "openclaw") with strict instructions:
      answer ONLY from the provided evidence; cite every claim as [n]
      matching the citations array; weight primary (customer-call) evidence
      and recent material; if evidence is thin or absent, say what the corpus
      does NOT yet cover instead of guessing; keep answers tight (<250 words
      unless asked for depth); note disagreement between sources when present.
   d. Store the exchange in `listening_chats(id, session_id, role, content,
      citations_json, created_at)` (idempotent DDL) so conversations can be
      reviewed/mined later.
3. Generous timeouts (gateway is slow); busy_timeout=15000; no streaming.

## Frontend (popup)

4. Floating button bottom-right of /listening (chat icon, subtle badge while
   answering). Click → popup panel (~380px wide, max-height ~70vh) with:
   - header: title "Ask the corpus", expand/contract toggle (expanded ≈
     centered 720px modal), clear-conversation, close
   - message list: user/assistant bubbles, assistant markdown via
     MarkdownView; under each answer a **Citations** block: [n] quote
     (truncated), author — source, date; clicking a citation opens its url
     in a new tab, else drills to Insights filtered by its cluster (reuse
     packet 7 wiring)
   - input: textarea + send (Enter sends, Shift+Enter newline), disabled
     while pending, loading indicator
   - **starter prompts** shown when conversation is empty (clickable chips):
     "Why are PI firms fatigued with AI demos?", "What do intake managers
     complain about most?", "What changed in the last month?", "What
     objections should I expect pitching a pilot to a managing partner?",
     "What vocabulary do operators use for records delays?"
   - conversation persists in sessionStorage (per-tab); session_id = random
     uuid stored alongside
5. Keep the popup self-contained (own component in the page file or
   colocated); do not disturb existing sections.

## Constraints
- LLM calls: gateway model "openclaw" only (no openclaw:main, no new keys).
- backend/main.py import pattern: try/except package fallback — preserve.
- Extraction backfill writes to the DB concurrently; busy_timeout everywhere.
- Validate backend on temp uvicorn :18001 (kill after; fuser -k 18001/tcp if
  PID hidden). Frontend: `npm --prefix frontend run build` only; no service
  restarts.
- ≤6 LLM calls during validation.

## Validation (include output)
- FTS query for "intake" returns ranked insight ids.
- curl chat endpoint with "Why are firms skeptical of AI demos?" — show JSON:
  answer cites [n] entries that exist in citations array; citations carry
  real insight ids/authors.
- Ask a question the corpus can't answer ("What do they think about crypto?")
  — answer admits the gap, no fabricated citations.
- `npm --prefix frontend run build` passes.

## Done when
Popup chat answers corpus questions with clickable citations, admits gaps,
stores history, builds clean.
