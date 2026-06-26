# PACKET A — Move ClickBeacon to the root layout (universal coverage)

**Repo / workdir:** `/home/pranav/getpossibleminds`. **You are Codex.** Frontend
only. **Do NOT commit, push, deploy, or restart anything.** Do NOT touch
`components/hero.tsx` (unrelated uncommitted WIP).

## Goal
Right now `<ClickBeacon>` is mounted per-page on 5 pages. Move it to the root
layout so **every** route fires the human-session beacon automatically (and new
pages get it for free).

## Scope
1. **`components/analytics/click-beacon.tsx`** — make `page` optional. When `page`
   is not provided, derive the slug at runtime from the pathname:
   `const page = explicitPage ?? (window.location.pathname.replace(/^\/+|\/+$/g,"") || "home");`
   Keep all existing behavior (lc param, session_id reuse, mount POST, sendBeacon
   on visibilitychange/pagehide, strict-mode + once guards, try/catch). It already
   runs client-side in `useEffect`, so reading `window.location.pathname` is fine.
2. **`app/layout.tsx`** — render `<ClickBeacon />` once inside `<body>` (it's a
   client component rendered by the server layout — fine in App Router). Add the
   import.
3. **Remove the 5 per-page mounts** + their imports so the beacon isn't double-fired:
   `app/consult/page.tsx`, `app/solutions/outbound-voice-ai/page.tsx`,
   `app/solutions/email-automation/page.tsx`, `app/solutions/lien-reduction/page.tsx`,
   `app/solutions/support-agent/page.tsx`. Remove ONLY the `<ClickBeacon .../>` line
   and the now-unused import; leave all other page content untouched.

## Guardrails
- Touch only: `components/analytics/click-beacon.tsx`, `app/layout.tsx`, and the
  5 page.tsx files (removal only). Nothing else. Not `hero.tsx`. No new deps.

## Validation (paste output)
- `npx tsc --noEmit` clean.
- `npm run build` succeeds.
- Show the final `click-beacon.tsx` and the `app/layout.tsx` diff.

## Finish
Report files changed + validation. Orchestrator reviews, commits, pushes (Vercel
auto-deploys).
