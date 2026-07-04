# PACKET — EmailTag Firms dashboard tab (possibleos frontend)

Workdir: `/home/pranav/possibleos`. Source spec: `docs/product/EMAILTAG_FIRMS_DASHBOARD_SPEC.md`
(read it fully first — it is the functional contract, verified against the live
EmailTag deployment). You are Codex, the implementer. Build **only** this tab.
Do not start any other task.

## Context you must respect

- This is a **frontend-only** feature in the Next.js 14 app under `frontend/`
  (App Router, TypeScript, Tailwind, Radix UI, `@tanstack/react-query`,
  `lucide-react`, path alias `@/*` → `frontend/`). It talks to an **external**
  API (EmailTag) via a same-origin proxy — there is **no possibleos backend
  change, no DB, no Python**.
- A **stale** client already exists at `frontend/lib/pifstats.ts` and is used by
  the existing `frontend/app/firms/page.tsx`. It hits emailtag directly with **no
  auth** and is missing vendor/export/enrich features. **Do NOT edit or delete
  `frontend/lib/pifstats.ts` and do NOT touch `frontend/app/firms/`** — the legacy
  `/firms` page must keep working unchanged. Your tab is a separate, complete,
  authenticated superset with its own client.

## Scope (build all)

1. **Proxy rewrite** — in `frontend/next.config.mjs`, ADD one rewrite to the
   existing `rewrites()` array (do not remove or reorder the existing `/api/:path*`
   and `/audio/:path*` entries):
   ```js
   { source: "/emailtag/:path*",
     destination: `${process.env.EMAILTAG_API_URL || "https://emailprocessing.mediflow360.com/api/v1"}/:path*` }
   ```
   This makes `/emailtag/pif-info/...` and `/emailtag/pifstats-auth/...` same-origin,
   so the `pifstats_session` cookie (SameSite=Lax) flows. All new client calls use
   base `/emailtag` and `credentials: "include"`.

2. **New API client** `frontend/lib/emailtag.ts` — typed functions + the interfaces
   from the spec (`PifInfoResponse` incl. `vendor_stack`, list/people responses,
   task responses, `ENTITY_TYPE_LABELS`). A single `emailtagFetch<T>(path, init)`
   helper that sets `credentials:"include"`, `Accept: application/json`, and throws
   a typed `EmailtagAuthError` on 401 so the UI can route to login. Cover: login,
   check, logout; list (all filter params from the spec), get-one, people; export
   (all + per-firm, as a `downloadEmailtagExport` blob helper honoring
   `Content-Disposition`); enrich-all + status poll; research / research-staff +
   status poll; detect-vendors (+ note: poll `getFirm` on `updated_at`);
   analyze-behavior.

3. **Route** `frontend/app/emailtag-firms/page.tsx` (+ any co-located components
   under `frontend/app/emailtag-firms/`). Client component. Implements the full
   **UI behaviour** section of the spec: login gate, filter bar (every list param),
   paginated table (page_size 25), expandable detail row (contacts, research grid,
   Front conversation IDs, **Vendor Stack** chips + Detect-vendors button, Run full
   enrichment + poll, per-firm Export JSON/CSV, Leadership/Staff/Extracted Contacts,
   raw-JSON viewers), and header bulk Export all → JSON/CSV. Use `react-query`,
   Tailwind, Radix and `lucide-react` to match the look/feel of
   `frontend/app/firms/page.tsx` (read it for styling patterns and helpers like
   `@/lib/utils` `cn`, tier color helpers). Guard every nullable field.

4. **Nav entry** — in `frontend/components/Nav.tsx` add ONE item to the `items`
   array (a `lucide-react` icon already imported or newly imported), e.g.
   `{ href: "/emailtag-firms", label: "EmailTag Firms", icon: Building2 }` placed
   right after the existing `/firms` entry. Do not restructure Nav.

## Repo conventions

- Match existing App Router page structure and the Tailwind class vocabulary used
  in `app/firms/page.tsx` (neutral palette, rounded-md, text-sm, etc.).
- Reuse `@/lib/utils` (`cn`) rather than adding a styling lib.
- No new npm dependencies. Use only what's already in `frontend/package.json`.
- Types: strict — no `any` in exported signatures (use `unknown` + narrowing).

## Guardrails (hard)

- **Additive only.** New files plus the two minimal edits named above
  (`next.config.mjs` +1 rewrite, `Nav.tsx` +1 item). Delete nothing.
- **Do NOT modify** any of these (unrelated in-flight WIP / legacy):
  `frontend/lib/pifstats.ts`, `frontend/lib/api.ts`, `frontend/app/firms/**`,
  `frontend/app/lead-gen/page.tsx`, `app/cli.py`, `app/services/lead_email_composer.py`,
  `tests/test_lead_email_composer.py`, `docs/CYBERNETIC_LEAD_GEN_CONCEPT.md`.
- **Do NOT `git commit` or `git push`.** The orchestrator commits.
- No service restarts, no `/etc`, no Docker, no `pip`, no `npm install`.
- No live network calls during build/validation (the proxy target is external; the
  build must not depend on it being reachable).

## Validation (run, report output)

From `frontend/`:
- `npx tsc --noEmit` — clean (no type errors).
- `npm run build` — succeeds (the new route compiles; `/emailtag-firms` appears in
  the route manifest).
Report the tail of both, and the list of files you created/edited.
