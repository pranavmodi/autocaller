# PACKET LEXVIS L5 — report v3: the five-page cut

Workdir: `/home/pranav/lexvisibility`. **The render target is
`docs/REPORT_V3_COPY.md` — read it first and follow it exactly.** Then
`app/pipeline.py` (render stage v2), `frontend/components/PublicReportPage.tsx`,
`frontend/app/globals.css` (print styles), `app/pdf.py`.

You are Codex. No commit/push/restarts/LLM calls. Deterministic transforms
only.

## Why

An end-to-end cold read found the v2 report buries its three persuasive facts
(Igarian 12, you 0; here's why; here's what it costs) under pipeline exhaust:
raw JSON, debug labels, a 107-row leaderboard with entity dupes, three
unreconciled dollar figures, duplicated blocks. v3 is a ~70% cut to five
pages per the copy deck, plus a sanitization layer so machine output can
never reach a prospect again.

## Scope

### 1. Payload sanitizers (render stage, unit-tested individually)

- **Leaderboard dedupe + filter:** merge rows by resolved `firm_id`, else by
  canonical domain, else by aggressive name normalization (case/punct/suffix
  folding + containment: "Jacoby & Meyers Accident & Injury Lawyers (Los
  Angeles)" merges into "Jacoby & Meyers"); sum appearances, keep best
  position. Drop non-law-firm rows: names matching medical/clinic patterns
  (`M.D`, `Medical`, `Surgery`, `Chiropractic`, `Imaging`, `Radiology`) and
  an operator-suppressible exclusion list stored on the run
  (`excluded_entities`, editable via override). Emit `top10` +
  `total_named_firms` count; full deduped list goes ONLY to the appendix
  payload.
- **Money normalizer:** all prospect-facing dollars rounded to nearest $1K
  and rendered as `$15K`, `$31K`, `$23K`, `$14K`; exact values remain in the
  appendix worksheet only. One anchor: the range; slot values derived and
  phrased per the deck ("roughly $14K of that").
- **Single denominator:** every prospect-facing count is X-of-20 (answering
  runs). No 33, no 12-of-20-win-condition duplication, no head-to-head counts
  outside the appendix.
- **Text scrubber applied to every prospect-facing string:** strip markdown
  syntax, internal labels (`scan_gap:`, `website_gap:`, `>=`), classifier
  phrases, field paths, float artifacts (round to 2dp max); drop cited-page
  titles matching challenge/bot patterns ("Just a moment", "Attention
  Required", "Access denied").
- **Dedupe blocks:** identical sentences/blocks may render at most once
  (the CTA button appears exactly twice by design: page 1 + page 5).
- **Accuracy-flag surfacing:** select flags whose claim/detail mentions the
  target firm; emit at most ONE, quoted cleanly (deck page 3 kicker). Drop
  the raw count entirely.

### 2. Render stage v3 payload

Replace `sections[]` with `pages[]` implementing the deck exactly: page ids
`verdict`, `see_it_yourself`, `who_wins_and_why`, `what_it_costs`,
`what_now`; each `{id, headline, body, traces}`. Keep hero_evidence
(screenshot slot + clean excerpt fallback), report token/QA gate unchanged.
New payload fields: `booking` {label, mailto (run-configurable payload field,
default per deck)}, `human_block` {name, org, line, photo_url|null,
placeholder: true} — all override-able via the existing override mechanism.
`appendix` payload: full matrix, full deduped leaderboard, per-competitor
cited domains, exact worksheet with the full assumption trail (rendered as a
clean table server-side — never raw JSON).

### 3. Frontend

- `/r/[token]`: five-page layout per the deck. The 20-cell grid visual (CSS
  grid, empty cells, caption). Verify box with copy button. Top-10 table with
  highlighted Block zero-row + footnote teaser. ✓/✗ source comparison table.
  Collapsible "How we calculated this" assumptions table (5 rows from the
  deck; values from payload). Three moves. Four day-ranged workstream cards
  ("Days 1–30: Site structure" + one outcome sentence). Human block
  (renders placeholder styling when `placeholder: true`). Booking button on
  page 1 and page 5. Dated trend note.
- `/r/[token]/appendix`: the appendix payload, plain and dense is fine;
  linked from pages 2 and 3; QA-gated same as the report.
- Remove "EXECUTIVE VIEW" labels; headlines are the deck's consequence
  headlines.
- Print CSS: five pages break cleanly; appendix NOT included in the PDF.

### 4. Tests

- Sanitizers: Jacoby variants merge to one row; medical rows dropped;
  "Just a moment" titles filtered; `scan_gap:` never in any prospect string;
  dollars rounded ($15K not $15,122); CTA exactly twice; one accuracy flag
  max, mentioning the firm; denominator-20 rule (no "33" outside appendix).
- Pages structure matches the deck ids/order; appendix gated pre-QA.
- Existing suite stays green (update assertions that referenced sections[]).

## Guardrails

- Follow the copy deck wording; do not invent new marketing copy.
- Additive pipeline contracts otherwise; no stage-logic changes outside
  render; no nginx/systemd changes. No `git commit`/`git push`.
- `pytest tests/ -q`, `npm run build`, `npm run lint` all clean; do NOT
  rerun the real Block LLP run (orchestrator does live verification).

## Report

Files changed, the sanitizer list with test names, pages schema, STOP.
