# PACKET — Human-session click beacon on all tracked landing pages

**Repo / workdir:** `/home/pranav/getpossibleminds` (the Possible Minds marketing
site, Next.js 14 App Router). **You are Codex, the implementer.** Frontend code +
validation only. **Do NOT commit, do NOT push, do NOT run `vercel`/deploy, do NOT
restart anything.** The orchestrator (Claude) reviews your diff, commits, and
deploys.

## Why
We drive tracked email traffic to marketing landing pages via possibleos short
links (`/a/`, `/c/`, `/s/` on `aiaudit.getpossibleminds.com`). The redirect click
is logged server-side, but email-security scanners (Proofpoint, Microsoft Safe
Links, Mimecast, Barracuda) fetch every URL in an email **without running page
JS**, so raw clicks are bot-dominated and useless as a human signal. A
`session_ready` beacon that only fires in a real browser gives the
human-confirmation signal. This packet adds that beacon to the landing pages.

The possibleos ingest endpoint is **already built and live**:
`POST {AUTOCALLER_API}/api/lead-gen/page-event` — public, accepts JSON
`{event, page, link_code, session_id, time_on_page_ms}`, returns
`{"ok":true,"attributed":bool}`. The `/c/` and `/s/` redirects append the
short-link code as the `lc` query param on the landing URL, which is how a session
attributes back to the email recipient.

## Scope

### 1. Shared beacon component — `components/analytics/click-beacon.tsx`
Create a client component `<ClickBeacon page="..." />` (`"use client"`). Behavior:

- Props: `page: string` (required, e.g. `"consult"`, `"outbound-voice-ai"`);
  `event?: string` default `"session_ready"`.
- Renders nothing (`return null`).
- API base: `const AUTOCALLER_API = process.env.NEXT_PUBLIC_AUTOCALLER_API_URL ||
  "https://autocaller.getpossibleminds.com";` (same pattern as
  `app/solutions/outbound-voice-ai/early-access-form.tsx` and
  `app/consult/consult-booking-form.tsx`).
- On mount (`useEffect`, runs once):
  - Read `lc` from `new URLSearchParams(window.location.search).get("lc")` (may be
    null — still beacon, just unattributed).
  - Get-or-create a `session_id`: reuse `sessionStorage["pm_session_id"]` if
    present, else `crypto.randomUUID()` and store it.
  - Record `mountedAt = Date.now()`.
  - POST `{event, page, link_code: lc, session_id, time_on_page_ms: 0}` to
    `${AUTOCALLER_API}/api/lead-gen/page-event` with
    `fetch(..., {method:"POST", headers:{"Content-Type":"application/json"},
    body, keepalive:true})`. Wrap in try/catch; never throw.
- On page leave — register `visibilitychange` (when `document.visibilityState ===
  "hidden"`) and `pagehide` listeners that fire once: POST the same payload but
  with `time_on_page_ms: Date.now() - mountedAt` using
  `navigator.sendBeacon(`${AUTOCALLER_API}/api/lead-gen/page-event`, new
  Blob([body], {type:"application/json"}))`, falling back to `fetch(..., {keepalive:true})`
  if `sendBeacon` is unavailable. Guard with a `sentLeave` ref so it only sends once.
  Clean up listeners in the effect's return.
- Strict-mode safe: guard the mount POST with a ref so React 18 double-invoke in
  dev doesn't double-send.

### 2. Mount the beacon on the tracked landing pages
Add `import ClickBeacon from "@/components/analytics/click-beacon";` and render
`<ClickBeacon page="<slug>" />` once near the top of each page's returned JSX
(inside the root wrapper). These are server components rendering a client child —
that is fine in App Router. Apply to **all five**:

- `app/consult/page.tsx` → `page="consult"`
- `app/solutions/outbound-voice-ai/page.tsx` → `page="outbound-voice-ai"`
- `app/solutions/email-automation/page.tsx` → `page="email-automation"`
- `app/solutions/lien-reduction/page.tsx` → `page="lien-reduction"`
- `app/solutions/support-agent/page.tsx` → `page="support-agent"`

## Guardrails
- Touch only: `components/analytics/click-beacon.tsx` (new) and the five
  `page.tsx` files above (import + one `<ClickBeacon/>` line each).
- **Do NOT modify `components/hero.tsx`** — it has unrelated uncommitted WIP.
- No new dependencies. No changes to copy/layout/styling beyond the one beacon line.
- Do not touch `early-access-form.tsx` or any backend.

## Validation (paste output in your report)
- `npx tsc --noEmit` — clean.
- `npm run build` — succeeds (or `npm run lint` if build is too slow in-sandbox;
  note which you ran).
- Show the final `components/analytics/click-beacon.tsx` in full and the diff of
  one page.tsx so the orchestrator can confirm placement.

## Finish
Report the file list, the validation output, and the beacon source. The
orchestrator will review against this scope, commit, and push (Vercel auto-deploys).
