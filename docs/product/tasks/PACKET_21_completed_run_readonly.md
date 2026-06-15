# Packet 21 — /lead-gen: completed runs become read-only history

You are the implementer in /home/pranav/autocaller. The /lead-gen batch
card currently renders every run as an actionable card with an
"Approve & send" button, an "Advanced" disclosure, and an amber "older
generated plan… generate today's action plan" banner. For a run that is
already fully sent, all of that is noise — approving an already-sent batch
is meaningless. Make completed runs render as compact read-only history.

## Read first
- frontend/app/lead-gen/page.tsx — the batch card lives in the component
  that renders `data.batch` + `data.items`. Relevant existing derived
  values already computed there: `counts` (summarizeItems), `sentItems`
  (items where isEmailSent), `canApprove`, `canQueue`, `hasQueueableItems`,
  `isOlderPlan` (= !isCaliforniaToday(data.batch.created_at)). The card was
  just simplified (3 stats, one primary "Approve & send", an "Advanced"
  disclosure with time-picker/variant/approve-without-send/regenerate/
  learning-proposal). The drafts list is `<DailyActionPlan>` and
  observations `<ObservationsPanel>` below the card — leave both intact.
- Helpers in the same file: isEmailSent, canQueueItem, summarizeItems,
  StatusPill, Metric.

## Behavior to implement

Define a run as **completed** when there are no further send actions to
take: `sentItems.length === data.items.length` OR (no item satisfies
`canQueueItem` AND `!canApprove`). Compute one boolean, e.g.
`isCompletedRun`, near the other derived flags.

When `isCompletedRun` is true, the card header area renders a **read-only
summary** instead of the action controls:
- Keep: the title row (batch name, id/composer/policy line, StatusPill).
- Replace the 3-stat line + primary button + Advanced section with a single
  compact summary line: `{n} sent · {bounces} bounced · {replies} replied`
  where bounces = items with outcome 'bounce', replies = items with outcome
  in (positive_reply, reply, referral, forwarded_internally,
  owner_introduction). Use the existing item.outcome field; if a helper
  doesn't exist, count inline from data.items.
- Show the run date (data.batch.created_at, formatted California date) as a
  muted label, e.g. "Completed · Jun 12, 2026".
- Do NOT render: Approve & send button, Advanced disclosure, the
  scheduled-start picker, composer-variant select, approve-without-send,
  regenerate drafts, learning-proposal button.
- The `<DailyActionPlan>` drafts list and `<ObservationsPanel>` STAY
  rendered below (read-only review of what went out).

The amber **"older generated plan… generate today's action plan" banner**
must only show for a stale plan that still has unsent work:
`isOlderPlan && !isCompletedRun && hasQueueableItems` (currently it shows
on any `isOlderPlan`). A completed older run is history, not a nag.

When `isCompletedRun` is false, behavior is unchanged from today (full
actionable card with the simplified controls).

## Constraints
- Frontend only. No backend, API, or schema changes. No new deps.
- Do NOT change the actionable-card layout for non-completed runs, the
  DailyActionPlan, ObservationsPanel, PreviewModal, or ObservationModal.
- Do NOT touch master-agent files, app/, or anything outside
  frontend/app/lead-gen/page.tsx (and frontend/lib/api.ts only if a tiny
  type addition is truly required — prefer not).
- Keep all existing imports used; remove none that are still referenced.
- TypeScript must compile: `npm --prefix frontend run build` passes.

## Validation (include output)
- `npm --prefix frontend run build` passes (paste the final lines).
- Describe, with the exact conditions, what renders for: (a) a completed
  run (all sent) — summary only, no buttons, no banner; (b) a stale unsent
  run — banner + actionable card; (c) today's fresh run — actionable card,
  no banner.
- Confirm DailyActionPlan + ObservationsPanel still render in all cases.

## Done when
Completed runs show a compact read-only summary with no action controls and
no nag banner; stale-but-unsent runs still show the banner + actions;
today's run is unchanged; build passes.
