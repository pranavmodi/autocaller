# Packet: Surface publication dates on blog post detail pages

## Repo
You are working in the getpossibleminds.com marketing site: a Next.js App Router
project. The working directory IS the website repo root (its `app/` directory is
at `./app`). Do NOT touch the autocaller repo.

## Context
The blog index at `app/blog/page.tsx` already defines a human-readable
publication date per post (e.g. `date: "June 12, 2026"`, `"May 25, 2026"`).
Individual blog post detail pages live at `app/blog/<slug>/page.tsx` and
currently do NOT display the publication date. A stale-or-undated blog hurts the
"this company is actively operating" signal; visible recent dates help it.

## Task
1. Make each blog post detail page (`app/blog/<slug>/page.tsx`) display its
   publication date prominently near the post H1 title, styled consistently with
   the existing dark theme + primary green (`#00ff41` / `text-primary`) accent
   used elsewhere on the site.
2. Source the date from a single source of truth. The dates currently live
   inline in `app/blog/page.tsx`. Prefer extracting the per-post metadata
   (slug -> title, date) into a shared module under `lib/` (e.g.
   `lib/blog.ts`) and have BOTH the index and the detail pages read from it, so
   dates never drift. If that refactor is too invasive, at minimum add the date
   to each detail page using the exact same date string already in the index.
3. Do not alter the prose/body content of any post. Only add the date display
   (and, if you choose, the small shared metadata refactor).
4. Keep the existing visual design language; do not restyle the pages.

## Verify
- Run the project's build (`npm run build` or `pnpm build` — detect which) and
  ensure it compiles with no new type errors.
- Confirm every post under `app/blog/*/page.tsx` renders a date near its title.

## Out of scope
- No new pages, no content rewrites, no dependency changes, no deploys.
- Do not commit unless the build passes; if you commit, use a clear message and
  do NOT push.
