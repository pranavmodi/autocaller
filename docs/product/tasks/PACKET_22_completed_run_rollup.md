# Packet 22 — Completed lead-gen runs: experiment rollup instead of item list

You are the implementer in /home/pranav/autocaller. Packet 21 (shipped) made
a completed daily-run render a compact summary line. But the per-item
`<DailyActionPlan>` list still renders below it for completed runs, which
duplicates the Comms log (every sent email already lives there) and dumps
pre-send selection score breakdowns that are useless once sent. Replace the
item list — for completed runs only — with a batch-as-experiment rollup
(persona × outcome and A/B-variant × outcome), which Comms structurally
cannot show. Active/today runs are unchanged.

## Read first
- frontend/app/lead-gen/page.tsx. The batch card already computes
  `isCompletedRun`, `counts`, `sentItems`, `bouncedCount`, `repliedCount`,
  `REPLY_OUTCOMES`, and `formatCaliforniaDate`. Below the card it renders
  `<DailyActionPlan items=... />` then `<ObservationsPanel ... />`.
- Item shape (from get_batch, already loaded into `data.items`): each item
  has top-level `persona` (string), `outcome` (string|null), and
  `reason.last_sent_composer_variant_key` (string|null = the A/B arm the
  sent email used). No API/backend change is needed — compute everything
  from `data.items` client-side.

## Build

### 1. Rollup component (same file or a small local component)
`<CompletedRunRollup items={data.items} />` rendering two small tables:

- **By A/B variant**: group items by `reason.last_sent_composer_variant_key`
  (null/empty → label "baseline"). Columns: variant, sent, replied, bounced.
- **By persona**: group items by `persona` (null/empty → "unknown").
  Columns: persona, sent, replied, bounced.

Per group: `sent` = items in the group whose outcome is not 'bounce'
(i.e. successfully went out — use the same definition the summary uses:
an item counts as sent if it has approval_status 'started' OR outcome is
non-bounce; mirror how `counts.started`/`sentItems` already classify —
reuse `isEmailSent` if it fits). `bounced` = outcome === 'bounce'.
`replied` = outcome in REPLY_OUTCOMES (already defined in the file:
positive_reply, reply, referral, forwarded_internally, owner_introduction).

Style: match the existing card aesthetic (neutral borders, text-sm/xs,
the tables in the Composer A/B page `frontend/app/composer-ab/page.tsx` are
a good reference). Right-align numeric columns. Sort rows by sent desc.
Zero-reply / zero-bounce cells show "0" in muted text; a non-zero
`replied` cell should read emerald, a non-zero `bounced` cell rose.

### 2. Wire into the card
When `isCompletedRun` is true:
- In the summary line, add a right-aligned link/button **"View emails in
  Comms →"** linking to `/comms` (plain Next `<Link href="/comms">`).
- Render `<CompletedRunRollup>` directly under the summary line, inside the
  `<section>` card.
- **Do NOT render `<DailyActionPlan>`** for completed runs (skip it).
  KEEP `<ObservationsPanel>` rendered (it shows reply/bounce events).

When `isCompletedRun` is false: unchanged — full item list via
`<DailyActionPlan>`, no rollup.

## Constraints
- Frontend only. No API/backend/schema change. No new deps.
- Do NOT change the active-run path, DailyActionPlan, ObservationsPanel,
  PreviewModal, ObservationModal, or the Packet-21 summary line/banner
  logic.
- Touch only frontend/app/lead-gen/page.tsx (a new component may live in
  the same file).
- TypeScript compiles: `npm --prefix frontend run build` passes. Do NOT run
  `next build` repeatedly/concurrently (it races on .next) — one build.

## Validation (include output)
- `npm --prefix frontend run build` passes (final lines).
- Describe what renders for a completed run (summary + Comms link + two
  rollup tables, NO item list, observations panel still present) vs an
  active run (unchanged full list, no rollup).
- For the live 06-12 batch (28fd2485…, 20 items: persona mix
  lien_settlement 10 / attorney 5 / intake 3 / records 2; variants baseline
  11 / subject-behavioral 6 / subject-pain-led 3; 1 bounce intake@fplpc),
  state the exact numbers your rollup would render so they can be eyeballed.

## Done when
Completed runs show the persona×outcome and variant×outcome rollup plus a
Comms link, with no duplicated per-item list; active runs unchanged; build
passes.
