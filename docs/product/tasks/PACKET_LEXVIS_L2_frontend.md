# PACKET LEXVIS L2 — ops stage rail + public report page (frontend)

Workdir: `/home/pranav/lexvisibility`. Depends on L1 (backend at
`app/`, API on port 8140 — read `app/main.py` for the exact routes and
payload shapes; do not guess). Source for report structure:
`docs/lexvisibility-2-spec_updated.md` §2.6 + §3.1, `docs/PILOT_ONE_PLAN.md`.

You are Codex. Build the Next.js frontend only. Do NOT commit/push, restart
services, or call LLMs.

## Stack

Next.js 14 App Router + Tailwind in `frontend/` (match the sibling repo
`/home/pranav/ai-visibility/frontend` conventions). Dev port 3140. API calls
via Next rewrite `/api/lexvis/:path*` → `http://127.0.0.1:8140/api/:path*`
(same-origin, no CORS).

## Page 1 — Ops console: `/runs` and `/runs/[id]` (the stage rail)

- `/runs`: table of runs (firm, status, current stage, created) → click into
  a run.
- `/runs/[id]`: the **horizontal stage rail** — 7 nodes (Ingest → Extract →
  Resolve → Score → Dollarize → Render → QA), each showing status color
  (pending / awaiting_review / done / failed / stale). Clicking a node opens
  its artifact inline below the rail:
  - pretty-printed JSON viewer (collapsible sections) + the content hash +
    version selector when multiple versions exist;
  - stage-specific niceties where cheap: extract/resolve stages render a
    table of mentions/resolutions; score stage renders the leaderboard
    table; render stage shows a "Preview report" link.
  - Action buttons per the API: **Advance** (enabled only on the
    awaiting_review stage), **Re-run stage**, and QA stage gets **Approve**.
  - Audit trail list (run_events) at the bottom.
- No auth for the pilot (localhost ops tool); note that in the README.

## Page 2 — Public report: `/r/[token]` (the artifact that books meetings)

Render the `GET /api/report/{token}` payload in the spec §2.6 fixed order,
**clinical memo design**: serif headings, generous margins, no gradients, no
logo wall, mobile-first at 390px.

1. Cover/verdict line (large, plain).
2. Hero evidence block: if `hero_screenshot` present render the image
   full-bleed; else render the hero query answer text as a quoted excerpt.
   Beneath it the **"Verify it yourself"** block: the exact query text with a
   copy-to-clipboard button.
3. The grid: queries × runs matrix, green cell = target present, gray =
   absent, click a cell → modal with that run's answer text + citations.
4. Metro leaderboard table, target firm's row highlighted.
5. The money: [low, high] monthly range headline + the full worksheet table
   from the dollarize payload (every input with source/basis/confidence).
6. "Why this is happening" mechanism section from the payload.
7. Trend note with the scan date.
8. Sticky footer CTA: "Worth 20 minutes? Reply and I'll send two times." —
   mailto link from payload CTA block.
- If the API returns 403 pending_qa, show a neutral "report not yet
  published" page.

## Validation (run, report)

- `npm run build` clean (typescript strict).
- `npm run lint` clean or pre-existing-warnings-only.
- Include a README section: how to run dev (backend 8140 + frontend 3140)
  and the rewrite config.

## Guardrails

- Do not modify anything under `app/`, `bin/`, or `tests/` (backend is L1's).
- No new deps beyond Next/Tailwind/clsx-tier utilities.
- Do NOT `git commit`/`git push`.

## Report (end of run)

Files created, routes, how to run both processes, build/lint output, STOP.
