# Autocaller — Product Vision

> **An always-on business development agent that finds the right law firms,
> discovers their operational pain, pitches what Possible Minds can actually
> build for them, and puts serious conversations on Pranav's calendar —
> without Pranav touching a dialer.**

---

## Why this exists

Possible Minds sells custom software and AI tooling to personal-injury law
firms — intake automation, medical-records retrieval, lien processing,
demand-letter drafting, client communication, operational tooling. The ICP
is real. The work is good. The bottleneck is top-of-funnel: nobody is
systematically finding firms, learning what hurts, and earning a 20-minute
conversation.

Hiring SDRs is expensive, slow to train, and fragile. Buying lead lists is
noise. Running outbound ourselves pulls Pranav out of the work that actually
wins deals.

**The autocaller is the SDR team.** Its entire existence is to produce
qualified 20-minute demo slots on Pranav's calendar — as few or as many per
week as the business needs — with enough context that Pranav walks into each
call knowing the firm's name, their top pain, and why Possible Minds is the
right call.

---

## The four jobs

The agent is only as good as its weakest link. All four must work for the
product to be useful; any broken link reduces the pipeline to zero.

### 1. Source the right people
Find decision-makers at PI firms who *could* buy: managing partners, owners,
principals, COOs, operations leads. Filter out solos-with-a-shingle (can't
afford), mega-firms (don't move fast enough), and non-PI adjacencies we
can't serve. The bar is not "has a phone number" — it's **"this is a firm we
could deliver real ROI to within 90 days."**

### 2. Discover the real pain
Cold-call the list. Open with permission. Listen for the operational knot
the firm actually lives with — intake conversion, records chasing, lien
spreadsheets, demand-letter bottleneck, client-update volume, docketing.
Quantify: hours a week, cost, missed revenue. The discovery call is not a
pitch; it's a diagnosis.

### 3. Pitch what we can credibly build
Possible Minds is not a point-product company — we build custom tools. The
agent must match the surfaced pain to a credible Possible Minds story:
"We shipped an intake bot for a 40-attorney firm that doubled their
after-hours conversion." Never promise what we haven't built. Never over-
fit to a pain we can't solve.

### 4. Book or release
If there's a fit and the person is a decision-maker: book a 20-minute slot
on Pranav's Cal.com, confirm email, end the call with a confirmed time. If
not a decision-maker: capture who is, end politely. If not interested: offer
a one-pager follow-up, end gracefully. The agent never books speculatively,
never promises meetings it didn't confirm, and never leaves the line silent.

---

## Principles (what makes this not a spam machine)

1. **Permission-first opening.** "Do you have 30 seconds?" — if no, pivot,
   don't press. Respect is a feature, not overhead.
2. **Honesty by default.** If asked "is this an AI?", the agent says yes.
   We are not impersonating a human. We are a well-prepared research call.
3. **Discovery > pitch.** Time spent listening is time earning trust.
4. **Compliance is load-bearing, not decorative.** TCPA scrubbing, DNC
   honoring, state-level calling-hour windows, opt-out on request, and a
   defensible consent log. No gray areas.
5. **Never promise what we can't deliver.** Pitch adjacent to real shipped
   work. If there's no analog, offer a diagnostic conversation instead.
6. **Pranav's calendar is sacred.** A booked meeting that turns out to be
   junk is worse than no meeting. Bar for booking is high.
7. **Every call produces a learning artifact.** Transcript + pain summary
   + disposition — even the wrong-number calls inform next week's list.

---

## Current state (v0.1 — what exists today)

The pipeline works end to end in proof-of-concept form:

- FastAPI daemon behind `autocaller.getpossibleminds.com` with real TLS.
- Twilio places calls, OpenAI Realtime handles the conversation.
- Prompt runs discovery, asks ONE quantifying follow-up, proposes a demo.
- Cal.com integration wired (not yet configured with real event type).
- CSV lead import, CLI ops, call recording + transcript storage.
- Safety rails: allowlist, live-call gate, per-state calling hours.

What's missing to be a real BD agent is in the roadmap below.

---

## Roadmap

### Phase 1 — Foundation (now → 2 weeks)
Goal: reliably handle one well-prepared call per hour, end to end, with
Pranav reviewing everything.

- Real Cal.com event type wired + booking confirmed on tested calls.
- Prompt quality pass: better objection handling, cleaner hand-off to
  "let me email you" when voicemail or no fit.
- Post-call summary pushed to Pranav daily (pain, disposition, next action).
- Fix SMS content + decide whether SMS stays on at all for cold outreach.
- DNC + TCPA baseline: minimum viable scrub, opt-out list persistence,
  state calling-hour gate (already wired), consent log.

### Phase 2 — Sourcing (2 → 6 weeks)
Goal: stop feeding CSVs by hand.

- Structured lead profile: firm size, practice area, revenue signal,
  decision-maker title, state.
- Integrate a B2B data source (Apollo / ZoomInfo / Clay) to pull a
  weekly prioritized list.
- Lead scoring: combine firmographic fit + recency signals (case filings,
  hiring activity) into a priority bucket.
- Bulk ingest → allowlist → dispatcher → call, without Pranav editing DB.

### Phase 3 — Quality (6 → 10 weeks)
Goal: every booked meeting is one Pranav actively wants to take.

- Per-call pre-brief: LLM pulls public info on firm and attorney
  (website, recent cases, LinkedIn) and injects into the AI's system
  prompt before dialing. No more generic "personal injury firms" opener.
- Pain → product matching: structured library of Possible Minds case
  studies indexed by pain. Agent picks the right one live.
- Conversation quality scoring: rubric-based review of recent calls,
  adjusts prompt based on what loses vs. what books.
- Concurrency: 3–5 parallel calls so pipeline scales without changing
  daily cost curve.

### Phase 4 — Autonomous (10+ weeks)
Goal: the agent runs the top of the funnel; Pranav only touches late stage.

- Multi-touch cadence: call → email → retry call → LinkedIn nudge, fully
  orchestrated per lead.
- CRM push: every outcome into HubSpot/Pipedrive/whatever we pick, with
  recording + transcript attached.
- Self-tuning prompts: A/B testing opening lines, pitch angles, timing,
  fed by which variations actually book.
- Daily KPI digest: Pranav gets one morning report — pipeline health,
  best-performing discovery questions, what's getting people to agree.

---

## Success metrics

What we optimize for, in priority order:

1. **Qualified demos booked per week** — the only number that matters.
2. **Demo-to-closed ratio after Pranav takes them** — are we booking the
   right people? If this drops, the agent is filling the calendar with junk
   and Phase 3 work is urgent.
3. **Cost per booked demo** — Twilio + OpenAI + Cal.com + data source.
   Target: under $25. If above $50, something's wrong.
4. **Opt-out rate** — above 5% means the approach is off-putting. Below
   1% is healthy.
5. **Daily dials → connects ratio** — detects list quality + calling-hour
   problems.

What we explicitly do **not** optimize for:
- Call volume as a goal in itself.
- Time spent on the phone.
- Feature breadth.

---

## Non-goals (things we are explicitly not building)

- **Voice cloning / human impersonation.** The agent identifies as AI.
- **A generic outbound SaaS product.** This is Possible Minds' in-house BD
  stack. If it becomes sellable later, that's a happy accident, not the plan.
- **Chatbot / inbound.** Cold outbound only. Inbound is Pranav + the
  existing channels.
- **Multilingual.** English-only for now. Spanish is a later bet.
- **Heavy web UI.** CLI-first. Dashboards later if needed.

---

## Open questions for Pranav

1. **Scope of target market.** PI-only, or do we include related practice
   areas (mass torts, workers' comp, medical malpractice)?
2. **Geography.** US-only makes TCPA clear; do we ever want to expand?
3. **Firm-size cutoffs.** What's the smallest firm worth calling? Largest?
4. **Lead budget.** What's a realistic weekly spend on Apollo / ZoomInfo
   tiers?
5. **Possible Minds messaging.** A tight paragraph on "who we are + what
   we've shipped" would meaningfully improve the pitch. The agent is
   currently improvising.
6. **Close-the-loop signal.** How does the agent learn which booked demos
   became deals? Manual feedback, HubSpot webhook, something else?
7. **Tone ceiling.** How aggressive is "too aggressive"? Does Pranav want
   warm and curious, or tight and transactional?

---

## One-line elevator

> A Possible Minds BD agent that lives on a phone line — it finds PI firms
> worth talking to, learns what's breaking for them, proposes what we'd
> build, and puts serious conversations on Pranav's calendar.
