# Decision log

The running record of **important decisions** made while working in this repo,
across every chat window / agent / session. It's the shared answer to "*why is
it this way?*" so future agents (and humans) don't re-litigate or accidentally
reverse a deliberate choice.

This is mandated by the **Decision log** standing rule in `CLAUDE.md`.

## How it's organized — by date, tagged by area
- **One file per UTC date:** `docs/decisions/YYYY-MM-DD.md`.
- Storage is **by date** because the log is an append-only stream of events;
  that's low-friction and conflict-free across parallel chat windows (each
  session just appends to today's file).
- **Each entry is tagged with an `Area`** so you still get the by-function-area
  view on demand: `grep -rn "Area: deliverability" docs/decisions/`.

## What to log (and what not to)
**Log** a decision when it's a *choice*, not routine work:
- Architecture / data-model / pipeline-design choices
- Policy, flag flips, tooling/transport selections (e.g. "keep Zoho, not Resend")
- Deliberate **deferrals** ("not building X now, because…")
- **Reversals / supersessions** of earlier decisions
- Anything a future agent could undo by accident without knowing the rationale

**Don't log:** routine bugfixes, refactors, renames, dependency bumps, or
day-to-day implementation. When unsure, one line is enough — err toward logging
strategic things, skip mechanical ones.

## Rules
1. **Append-only.** Never edit or delete a past decision. To change one, add a
   NEW entry and set the old one's `Status: superseded by <new id>`.
2. **Incremental.** Add entries as decisions are made, or at end of session — do
   not dump weeks of history at once.
3. **Tag the `Area`** on every entry (taxonomy below).
4. Keep entries short. Link commits/PRs/flags where useful.

## Entry format
Append entries under the day's file. Use a stable id `D-YYYY-MM-DD-NN`.

```markdown
## D-2026-06-17-01 — <short decision title>
- **Area:** deliverability
- **Status:** accepted        <!-- accepted | superseded by D-… | reversed -->
- **Decision:** <what we decided, one or two sentences>
- **Why:** <the rationale / what it beats>
- **Refs:** <commit sha / flag / file / PR> (optional)
```

### Area taxonomy (keep it small)
`lead-gen` · `deliverability` · `data-arch` · `website` · `infra` · `process` ·
`product`

(If something truly doesn't fit, add a new area here in the same change.)

## Finding things
- By topic: `grep -rn "Area: lead-gen" docs/decisions/`
- Latest: newest dated file.
- A decision's history: search its id and any `superseded by` references.
