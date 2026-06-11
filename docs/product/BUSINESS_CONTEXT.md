# Business Context — Possible Minds GTM (operator brain dump)

*Captured 2026-06-11 from Pranav, verbatim intent preserved. This is the "why"
behind the listening system, the autocaller, and the learning loop. Read this
before proposing changes to any of them.*

## The system of systems

- **Listening system** (`/listening`, MC + autocaller CLI): exists to get into
  the deep mindset of the real issues of PI firm decision makers. Not research
  for its own sake — it feeds outreach quality.
- **Autocaller / Possible OS**: executes outreach (email sequences, voice
  calls, follow-ups) and the operational pipeline (firms, contacts, consults).
- **Learning system** (cybernetic lead-gen loop): the OODA loop —
  observe → orient → decide → act — that learns from market feedback and
  changes future behavior. The listening system is Observe/Orient for the
  market's voice; delivery/reply/booking signals are Observe for our actions.

## The success signal

The feedback that tells us the listening system works: **engagement from our
ICP** — email replies, phone conversations, consultations booked. Not opens,
not volume. North-star: **maximize the pipeline of PI people to talk to.**

## Lead source and credibility asset

- **Primary lead source: Precise Imaging's Front email inbox.** Front has an
  API that returns the firm contacts who have interacted with Precise Imaging.
  (MC already has `front_conversations` / `front_messages` tables; autocaller
  todo #18 "Front Read-Only Enrichment" is not started.)
- **Track record with Precise** (tools we built and operate for them):
  - email triage
  - voice calling for intake
  - website chatbot
- **The credibility play**: leverage this track record in outreach to PI firms
  — "we already run this for a company serving 1,900 PI firms" — to cut
  through vendor skepticism / AI-demo fatigue (see GTM_STRATEGY_2026-06.md:
  Precise distribution is unavailable, but the proof point remains).

## Standing strategic context (from GTM_STRATEGY_2026-06.md)

- ICP Tier 1: mid-size, ad-spend-heavy, auto-accident-concentrated PI firms on
  modern case management, vendor-using.
- Wedge over bespoke: lead with one sharp outcome (after-hours intake capture,
  records/lien workflows) — the corpus now confirms records chasing and intake
  overload as top pain clusters.
- Demo fatigue is mistrust of vendors who don't understand operations; the
  cure is demonstrated understanding (insight-led outreach), which the
  listening corpus exists to supply.

## Open questions (asked 2026-06-11, answers to be recorded below)

1. Boundaries on using Precise's Front inbox data for our own lead gen?
2. Can outreach publicly name Precise + cite numbers, or anonymized only?
3. Primary KPI definition + current target volume for "pipeline of PI people
   to talk to"?
4. Any referenceable customers besides Precise?

## Answers (2026-06-11)

1. **Front data**: full use of firm contacts and any other Precise data for
   lead gen. Revised 2026-06-11: storing PHI/patient data in our own database
   is acceptable; the hard requirement is **patient data must never leak into
   outbound outreach** (emails, calls, published content). Enforcement lives
   at egress (outreach policy check), not at ingestion.
2. **Credibility**: fully attributable — name Precise Imaging and cite the
   numbers (520 hrs/month, 73% automation, the tools we run).
3. **KPI**: operator asked us to propose what maximizes learning rate (see
   audit recommendation: learn on qualified replies, report on booked
   conversations).
4. **References**: none besides Precise yet.
