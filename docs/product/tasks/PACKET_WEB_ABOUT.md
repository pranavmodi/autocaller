# Packet: About page — real founder identity

## Repo
getpossibleminds.com marketing site, Next.js 14 App Router (dark theme, primary
green). Edit `app/about/page.tsx`. Do NOT touch the autocaller repo.

## CRITICAL TRUTHFULNESS CONSTRAINT
Use ONLY the founder facts below. Do not invent titles, dates, employers, or
metrics. Where a real asset is missing (LinkedIn URL, headshot photo), insert a
clearly-marked placeholder with a `TODO` comment — do NOT fabricate a URL or use
a random stock photo of a person.

## Task
Add a real "Founder" section to `app/about/page.tsx` (keep the existing
"What we build / How we work / Where we deliver / Why it works" cards). Also add a
small "Founded 2023" / "Bengaluru, India" cue near the top so the company reads as
a real, located, dated entity.

### Founder facts (all true, from the founder's profile)
- Name: **Pranav Modi**
- Title: **Founder, Possible Minds**
- Location: **Bengaluru, India**
- Company founded: **December 2023**
- Bio (you may lightly reword for flow, keep all facts):
  "Pranav founded Possible Minds in December 2023. Before that he spent close to
  five years at McKinsey & Company building machine-learning solutions that
  delivered over $100M in impact across retail, pharma, manufacturing, and
  transport. He then built AI systems to detect cancer in tissue images at
  Definiens, led data-science work at Near, and was a product manager on the data
  platform at Expedia Group. Possible Minds brings that production-ML and product
  background to the operational workflows of personal injury firms and the medical
  imaging centers that serve them."
- Short credential line you may surface as a highlight: "Ex-McKinsey data
  scientist. $100M+ in ML/AI impact before founding Possible Minds."

### Placeholders (do NOT fabricate)
- LinkedIn: render a "Connect on LinkedIn" link whose `href` is the constant
  `LINKEDIN_URL` — add `export const LINKEDIN_URL = "https://www.linkedin.com/in/REPLACE_ME";`
  to `lib/constants.ts` with a `// TODO: real LinkedIn vanity URL` comment, and
  import it. (Operator will fill the real URL.)
- Headshot: reserve a square avatar slot using a styled placeholder (e.g. initials
  "PM" in a bordered circle, or a `next/image` referencing
  `/founder-placeholder.png` that does not yet exist) with a `// TODO: real
  headshot` comment. Do NOT use a stock photo of a person.

## Style
Match existing About cards: `rounded-2xl border border-primary/25 bg-[#04150d]
p-6`, `text-primary` headings, `#00ff41` accents.

## Verify
- `npm run build` compiles with no new type errors.
- `/about` renders the founder section with the placeholders clearly visible.

## Out of scope
- Edit only `app/about/page.tsx` and `lib/constants.ts`. No deploys. Do not commit
  unless build passes; if you commit, scope to those files and do NOT push.
