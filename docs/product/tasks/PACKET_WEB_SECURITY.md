# Packet: Add a Security & Privacy page (truthful HIPAA-in-progress posture)

## Repo
You are working in the getpossibleminds.com marketing site: a Next.js 14 App
Router project (Tailwind, dark theme, primary green `#00ff41` / `text-primary`).
The working directory IS the website repo root. Do NOT touch the autocaller repo.

## CRITICAL TRUTHFULNESS CONSTRAINT (read first)
This page concerns a company that touches medical records and client PII.
You MUST use ONLY the approved copy below. Do NOT invent, embellish, or add any
compliance claim. Specifically FORBIDDEN unless it appears verbatim below:
- "HIPAA compliant", "fully compliant", "certified", "SOC 2", "ISO 27001"
- any claim that BAAs are available/signed today
- any specific security certification, audit, pen-test, or uptime guarantee
HIPAA compliance is IN PROGRESS, not complete. Word it exactly as given.

## Task
1. Create a new route `app/security/page.tsx` titled "Security & Privacy", styled
   to match the existing site (see `app/about/page.tsx` for the section/card
   pattern: `bg-black`, hero with radial primary glow, `rounded-2xl border
   border-primary/25 bg-[#04150d] p-6` cards, `text-primary` headings,
   `text-[#00ff41]` H1). Add a `Metadata` export (title + description) like other
   pages, importing `SITE_NAME` from `@/lib/constants`.
2. Use this approved content, organized as a short hero + cards. You may adjust
   wording lightly for flow but MUST NOT add claims beyond these facts:

   HERO
   - Eyebrow: "Security & Privacy"
   - H1: "Built for regulated operations"
   - Subhead: "We build AI systems for healthcare and legal workflows. Protecting
     the sensitive data those workflows touch is a first-class design constraint,
     not an afterthought."

   CARD 1 — "Your data stays in your accounts"
   "Everything we build runs on infrastructure and accounts you own and control:
   your cloud, your email, your telephony, your API keys. Your data lives in your
   systems, not ours. If we ever stepped away, your system keeps running."

   CARD 2 — "You own what we build"
   "The source code and documentation for what we build are yours. No black box
   and no lock-in: your team, or any engineer you choose, can operate and extend
   it."

   CARD 3 — "Controls for sensitive data"
   "For workflows that touch PHI or client data, we design with least-privilege
   access, audit trails on automated actions, automated checks that guard against
   sensitive data leaving in outbound messages, and human review on sensitive or
   low-confidence edge cases."

   CARD 4 — "HIPAA"
   "We follow HIPAA-aligned practices, and formal HIPAA compliance is actively in
   progress. We're glad to walk your team through our current controls and our
   compliance roadmap, including Business Associate Agreements."

   CARD 5 — "Privacy"
   "We collect only what we need to operate the systems we build and to respond to
   inquiries. We do not sell personal data. Questions about data handling? Email
   hello@possibleminds.ai."

3. Add a link to `/security` in the site navigation and/or footer. Inspect
   `lib/navigation.ts` and the header/footer components to find the right place;
   match the existing link style. If a footer "company"/legal link group exists,
   add it there; otherwise add to the primary nav.

## Verify
- Run `npm run build` and ensure it compiles with no new type errors.
- Confirm `/security` renders and the nav/footer link resolves to it.

## Out of scope
- No other pages, no copy changes elsewhere, no dependency changes, no deploys.
- Do not commit unless the build passes; if you commit, use a clear message and
  do NOT push.
