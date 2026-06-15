# Packet: Homepage — Precise Imaging stability anchor + de-risk teaser

## Repo
getpossibleminds.com marketing site, Next.js 14 App Router (Tailwind, dark theme,
primary green `#00ff41` / `text-primary`). Working dir IS the repo root. The
homepage is `app/page.tsx` (it renders a `Hero` from `components/hero`, then
case-study sections). Do NOT touch the autocaller repo.

## CRITICAL TRUTHFULNESS CONSTRAINT
Use ONLY the approved copy below. The Precise Imaging numbers are operator-cleared
and may be stated. You may name Precise Imaging as a track record, but you MUST
NOT imply Precise endorses, partners with, or distributes Possible Minds. Do not
invent other clients, numbers, or guarantees.

## Task — make two additions to the homepage (`app/page.tsx`)

### 1. Precise Imaging stability anchor (place prominently near the top)
Add a band/section immediately AFTER the `<Hero />` and before the first
case-study section. Inspect `components/hero.tsx` first to match styling. Use:

- Eyebrow: "Proven in production at scale"
- Headline: "The automation behind Precise Imaging runs on our systems."
- Body: "We build and run the automation behind Precise Imaging's operations: a
  system that triages roughly 600 inbound emails a day, auto-handles about 73% of
  that volume, and saves on the order of 520 staff-hours a month across the
  ~1,900 personal injury firms Precise serves. It has run in production for years.
  When you work with us, you are not betting on a prototype."
- Optionally render the three figures as stat tiles (600 emails/day · 73%
  auto-handled · ~520 staff-hours/month) using the existing card styling.

### 2. "Built to outlast us" de-risk teaser (place lower, before the final CTA)
A short two-point section that names and defeats the vendor-stability objection,
linking to the Security page. Use:

- Heading: "Built to outlast us"
- Point 1 — "Runs on your accounts": "Everything we build runs on infrastructure
  you own and control. If we ever stepped away, your system keeps running."
- Point 2 — "You own what we build": "The source code and documentation are
  yours. No black box, no lock-in."
- A link "Security & ownership →" pointing to `/security` (this route exists).

### 3. Social proof + reference offer (SCAFFOLD with placeholders)
Add a short "What clients say" area near the case studies. Since real
testimonial/logo assets are not yet provided, scaffold it so the operator can
drop them in:
- One testimonial card with clearly-marked placeholder text in a `TODO` comment
  (e.g. quote `"{{TESTIMONIAL_QUOTE}}"`, attribution `"{{NAME}}, {{TITLE}},
  {{FIRM}}"`). Do NOT invent a quote, name, or firm.
- A logo row placeholder (a `TODO` comment + empty styled slots), no fabricated
  logos.
- A real, usable line: "Want to talk to a firm already running this? We'll
  connect you with a reference." with a link to `/consult`.

## Style
Match existing homepage sections (`max-w-6xl`, `rounded-2xl border
border-primary/...`, `text-primary` headings, dark `#04150d` cards). Do not
restyle existing sections or change the Hero's existing copy.

## Verify
- `npm run build` compiles with no new type errors.
- Both additions render on `/` and the `/security` link resolves.

## Out of scope
- Only edit `app/page.tsx` (and read-only inspect `components/hero.tsx`). No other
  files, no dependency changes, no deploys. Do not commit unless build passes; if
  you commit, scope it to `app/page.tsx` only and do NOT push.
