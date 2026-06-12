# Packet 9 — Precise quote provenance: click a quote, see it in its source

You are the implementer in /root/.openclaw/workspace/mission-control. Operator
feedback: clicking an exec-view quote should take you to the PRECISE source of
the quote, not a generic section. Same for chatbot citations.

## Read first
- backend/listening.py: items endpoints, insights schema (insight.item_id),
  exec endpoint (quotes carry insight_id)
- frontend/src/app/listening/page.tsx: exec card quote click handling, chat
  popup citation click handling, CollapsibleSection

## Tasks
1. **Backend** `GET /api/listening/items/{item_id}` → full item: id, source
   kind/name, author, title, url, published_at, is_primary, status, raw_text,
   plus its insights (id, type, cluster, quote). Also ensure the exec quotes
   payload and chat citations include `item_id` (add if missing).
2. **Frontend — provenance modal**: clicking a quote (exec "Voice of the
   market") or a chat citation opens a modal:
   - header: source name, author, date, kind badge, primary badge if
     is_primary, external-link button when url exists
   - body: the item's raw_text rendered scrollable, with THE QUOTE highlighted
     (mark/bg-amber) and auto-scrolled into view on open; if the quote string
     isn't found verbatim (whitespace drift), highlight the closest match by
     normalized search, else show quote pinned at top with a "shown out of
     context" note
   - footer: the item's other insights as small chips (type + truncated
     quote); clicking one re-highlights that quote in the text
   - close on Esc / backdrop click
3. Long transcripts: render raw_text lazily/efficiently (it can be 24k chars);
   simple windowing or just a scrollable pre block is fine — no new deps.
4. Keep existing URL-open behavior as the external-link button inside the
   modal rather than the primary click action.

## Constraints
- Frontend validated by `npm --prefix frontend run build` only; backend on
  temp uvicorn :18001 (kill after; fuser -k 18001/tcp if PID hidden); no
  service restarts; busy_timeout=15000; no new dependencies; no LLM calls.

## Validation (include output)
- curl the item endpoint for one customer-call item — show id/author/insights
  count and that raw_text is present.
- Confirm exec quotes + chat citations now carry item_id.
- `npm --prefix frontend run build` passes.
- Describe the modal flow for (a) a customer-call quote (no url) and (b) a
  Substack quote (url present).

## Done when
Clicking any quote/citation opens its source item with the quote highlighted
in context; external link preserved when a url exists.
