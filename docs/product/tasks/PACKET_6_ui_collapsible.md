# Packet 6 — /listening UI: collapsible sections + in-UI explanations

You are the implementer in /root/.openclaw/workspace/mission-control. Operator
feedback driving this: "too much info — make each section collapsible, and
explain in the UI what's what."

## Read first
- frontend/src/app/listening/page.tsx (the whole page)
- One other page for conventions (e.g. src/app/goals)

## Tasks
1. Add a reusable `CollapsibleSection` component in the page file (or
   colocated): props `title`, `description` (one plain-English sentence shown
   under the title in muted text), `defaultOpen`, `badge?` (e.g. a count).
   Chevron toggle, Tailwind-styled to match the existing dark panels.
   Persist each section's open/closed state in localStorage
   (`listening.section.<key>`).
2. Wrap every major section of the page in it, with these descriptions
   (tighten wording if needed, keep the meaning):
   - **Overview** (stat cards): "Totals across the listening pipeline: where
     content comes in (sources), what's been collected (items), what was
     learned (insights), and the weekly synthesis (briefs)."
   - **Mindset Brief**: "The weekly synthesized read on PI-operator thinking —
     clusters, objections, vocabulary, personas — generated from all insights.
     Pick a version to compare weeks." Default OPEN.
   - **Paste signal**: "Drop in a LinkedIn post, call notes, or anything you
     read — it becomes a source item and is mined for insights immediately."
   - **Source Freshness / All sources**: "Everything the system reads:
     scraped feeds and subreddits, transcribed podcasts, crawled blogs, job
     listings, and pasted material — with when each was last read."
   - **Items**: "Raw collected content, one row per post/transcript-chunk/
     listing, with extraction status (new → extracted/skipped)."
   - **Insights**: "Verbatim quotes mined from items, typed (pain point,
     objection, vocabulary…) and attributed to who feels it."
   - **Health & Alerts**: "The system watching itself: stale sources, spikes,
     tracked-leader posts, name mentions, and proposed new voices to follow."
   - Default state: Brief + Health/Alerts open; everything else collapsed.
3. Keep all existing functionality (filters, paste form, alert actions,
   version picker) working inside the collapsed/expanded wrappers.

## Constraints
- Frontend only. Do NOT touch backend/, deploy/, or any other page.
- Validate with `npm --prefix frontend run build` ONLY; do not restart the
  :3001 service (orchestrator does that).
- No new dependencies.

## Validation (include output)
- `npm --prefix frontend run build` passes and includes /listening.
- Describe (or DOM-dump) the rendered section order and default open states.

## Done when
Page builds; every section is collapsible with a one-line explanation; state
persists across reloads via localStorage.
