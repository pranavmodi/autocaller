# Freeware Wedge GTM Strategy — Possible Minds

> **The portfolio strategy for Possible Minds' free, firm-specific diagnostic
> tools.** Each tool is a standalone insight-led wedge that earns a conversation
> with a demo-fatigued PI firm by telling them something true and useful about
> their own firm *before* asking for anything. Bespoke AI work is the expansion,
> not the entry.**

This is the cross-tool umbrella doc. Individual tools have their own specs; this
doc explains how they fit together into one go-to-market motion and what every
new freeware tool must inherit.

---

## Why freeware is the wedge

The GTM constraint is established in
[`GTM_STRATEGY_2026-06.md`](./GTM_STRATEGY_2026-06.md): the Precise distribution
channel is gone, cold + "we build bespoke AI agents" is one of the hardest
combinations in B2B, and PI firms are exhausted — not by AI, but by **vendors who
lead with a demo and don't understand their operation.**

The resolution is to **lead with insight, not a demo.** A free, firm-specific
diagnostic:

1. **Cuts through demo fatigue** — it demonstrates understanding before asking for
   anything. The owner's reaction is itself research.
2. **Makes cold outreach convertible** — the outbound email carries one
   verifiable, firm-specific finding and a link to a finished report, not a pitch.
3. **Doubles as the lead-gen sensor** — every scan/report is a labeled data point
   that feeds the cybernetic lead-gen loop
   ([`../CYBERNETIC_LEAD_GEN_CONCEPT.md`](../CYBERNETIC_LEAD_GEN_CONCEPT.md)).
4. **Turns "not ready" into pipeline** — a firm that scores poorly is not a lost
   lead; the blockers the diagnostic surfaces *are* the roadmap of paid work.

The wedge is never "we built an AI tool." The wedge is a sharp question the owner
can't answer on their own and wants to.

---

## The tool portfolio

Each tool answers a different question the PI owner cares about. They share one
delivery pattern, one lead-gen loop, and one brand.

| Tool | Domain | The question it answers | Status |
|------|--------|--------------------------|--------|
| **AI Search Visibility** (aiscan) | `aiscan.getpossibleminds.com` | "When someone in your city asks an AI assistant who to call after a crash, are you in the answer?" | Spec'd / building — see [`AI_SEARCH_VISIBILITY_TOOL_SPEC.md`](./AI_SEARCH_VISIBILITY_TOOL_SPEC.md) |
| **AI Readiness Audit** (aiaudit) | `aiaudit.getpossibleminds.com` | "Is your firm actually able to put AI to work without it failing — and if not, what's blocking you?" | Spec + research — see [`/home/pranav/AIAudit/README.md`](../../../AIAudit/README.md) |
| _future tools_ | `*.getpossibleminds.com` | one more abstract-but-acute PI pain made concrete and firm-specific | Backlog in [`PI_FOUNDER_PERSONA_AND_FREEWARE_IDEAS.md`](./PI_FOUNDER_PERSONA_AND_FREEWARE_IDEAS.md) (top: Ghost Lead Test, Intake Conversion Teardown) |

**aiscan** addresses an *external* gap (client-acquisition visibility in an
emerging channel). **aiaudit** addresses an *internal* gap (operational readiness;
~85% of AI initiatives miss their goals on data readiness, workflow integration,
and undefined outcomes — not the model). Together they bracket the buyer's two
biggest AI anxieties: "am I being left behind in how clients find lawyers?" and
"if I try AI, will it just fail like everyone says?"

---

## What every freeware tool must inherit (the franchise rules)

A new tool is only part of this strategy if it satisfies all of these. Treat this
as the checklist for proposing the next one.

1. **Insight-led, not demo-led.** It must tell the owner something true and
   specific about *their* firm. If it can't be personalized, it's a brochure, not
   a wedge.
2. **Defensible claims only.** No overclaiming (e.g. aiscan is "standardized AI
   search checks," never "official ChatGPT ranking access"). The single fastest
   way to reinforce demo fatigue is to feel like a gimmick.
3. **"Not ready / not visible" is a feature.** Volunteering the bad news and the
   boundaries is the Fadell "best marketing tells the truth" move — it builds
   credibility faster than any capability claim, and the gaps are the paid work.
4. **Batch pre-generation for named targets.** The default path scans a firm
   *before* the outbound email; the email carries one verifiable finding and links
   to a finished report. Do not make known leads click to start a scan. Gate live
   on-demand scans (cold organic visitors) behind caps + abuse controls.
5. **CLI-first, slots into the lead-gen loop.** Same operator contract as the rest
   of Possible OS (see repo `CLAUDE.md` golden rule). Reports become observations,
   email-capture and replies become feedback signals.
6. **A launch gate + an explicit kill criterion.** Calibrate against manual
   baselines before outbound; define up front the accuracy bar below which
   outbound halts (aiscan: <50% of first 50 reports yielding a recognizable
   competitor list ⇒ stop and fix extraction).
7. **Free → monitoring → execution ladder.** The free diagnostic is the
   loss-leader top of a land-and-expand path: recurring monitoring and the
   execution/build work are where revenue lives.

---

## The shared funnel

```text
Free diagnostic link (in outbound email / LinkedIn, pre-generated per target)
  -> owner clicks (curiosity, not a pitch)
  -> firm-specific report with one verifiable finding + prioritized fixes
  -> email capture for full report
  -> reply / follow-up conversation (insight-led, not demo-led)
  -> consult / booked call
  -> scoped wedge engagement (fix the gap the diagnostic found)
  -> bespoke expansion + recurring monitoring/execution
```

The free tool is the **land**; bespoke build + monitoring/execution is the
**expand**. Each report is also a research artifact that sharpens the ICP, the
vocabulary glossary, and the next email.

---

## How this fits the broader GTM

- **Channel hierarchy** (from `GTM_STRATEGY_2026-06.md`): replicate the
  "trusted non-competitive vendor" channel (lien funders, record-retrieval,
  case-management marketplaces) first; lookalike outbound second; broad cold
  last. **The freeware tools make every one of those channels convertible** by
  giving each touch a concrete, useful artifact instead of a pitch.
- **ICP**: mid-size (~5–30 attorney), ad-spend-heavy, auto-accident-concentrated
  PI firms on a modern case-management system. The diagnostics are tuned to make
  *this* firm's pain legible; tools that only work for everyone work for no one.
- **Proof**: the Precise case study (520 staff hours/month, 73% automation)
  anchors every report's "here's what fixing this looks like" section.

---

## Portfolio success metrics

Per-tool metrics live in each tool's spec. Across the portfolio, what we optimize:

1. **Consult / booked-call rate** from diagnostic recipients — the only number
   that matters.
2. **Link-click → report → email-capture → reply** funnel, per tool and per
   channel (detects which wedge and which message convert).
3. **% of reports with at least one meaningful, accurate firm-specific finding** —
   the credibility floor; if this drops, the wedge becomes a gimmick.
4. **Wedge → bespoke expansion rate** — does the free diagnostic actually lead to
   paid work?
5. **Cost per diagnostic** — pre-generation + API budget per scanned firm.

What we explicitly do **not** optimize: number of tools, scan volume as a goal in
itself, or feature breadth within any single tool (3–4 tentpoles max per tool —
past that it's gobbledygook).

---

## Related docs

- Tool specs: [`AI_SEARCH_VISIBILITY_TOOL_SPEC.md`](./AI_SEARCH_VISIBILITY_TOOL_SPEC.md),
  AIAudit repo (`/home/pranav/AIAudit/docs/`).
- Strategic reasoning: [`GTM_STRATEGY_2026-06.md`](./GTM_STRATEGY_2026-06.md).
- Lead-gen loop the tools feed: [`../CYBERNETIC_LEAD_GEN_CONCEPT.md`](../CYBERNETIC_LEAD_GEN_CONCEPT.md).
- Outbound BD function: [`../VISION.md`](../VISION.md).
- Buyer mindset / personas: [`PI_FIRM_PERSONAS.md`](./PI_FIRM_PERSONAS.md).
- Founder persona + new-tool backlog: [`PI_FOUNDER_PERSONA_AND_FREEWARE_IDEAS.md`](./PI_FOUNDER_PERSONA_AND_FREEWARE_IDEAS.md).
</content>
