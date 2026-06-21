# PI Founder Persona + Freeware Idea Backlog

> Companion to [`FREEWARE_GTM_STRATEGY.md`](./FREEWARE_GTM_STRATEGY.md). This doc
> grounds the freeware portfolio in (a) a research-backed picture of the PI
> firm-owner buyer and (b) a ranked backlog of candidate free diagnostic tools,
> each scored against the franchise rules. Sources are external research run
> 2026-06-21 (links at bottom) cross-checked against our own
> [`PI_FIRM_PERSONAS.md`](./PI_FIRM_PERSONAS.md) and
> [`BUSINESS_CONTEXT.md`](./BUSINESS_CONTEXT.md).

---

## The founder persona (research-grounded)

The economic buyer for a Tier-1 PI firm is the **founder / managing partner** —
and the single most important fact about them is an identity in tension:

- **Trial lawyer first, CEO second.** The defining growth move in the literature
  is the shift "from a lawyer who practices law to a CEO who builds a business"
  (Maximum Lawyer / John Morgan / Chad Dudley's *Seven Disciplines*). Most owners
  are mid-transition: they think like litigators but are judged on throughput and
  margin. They respond to **business arithmetic**, not technical cleverness.
- **Runs a contingency-fee, lumpy-cash-flow machine.** Revenue is signed cases →
  settled cases → collected fees, with long delays. "Hire against collected fees,
  not intake volume; payroll trails cash." A file sitting idle isn't a soft cost —
  it's a delayed settlement check, multiplied across 50–100 active cases. **Cycle
  time *is* cash flow.** This is the frame every ROI claim must land in.
- **Acutely cost-per-case sensitive.** PI is the most expensive ad market in law:
  ~$300 CPC on Google, ~$2,500–3,000 cost per signed case via PPC (can hit $7,500
  at poor conversion), ~$960 via LSA. Owners obsess over the funnel because every
  point of intake conversion is worth thousands. Anything that quantifies a leak
  in that funnel gets attention instantly.
- **Demo-fatigued and liability-reflexive.** ~37% already use generative AI (ahead
  of the profession), but 44% have no AI governance policy; bar rules (ABA 512,
  CA/FL/NY guidance) and 367 court cases with AI fabrications in 2025 (220+ more in
  Q1 2026) make "AI" ping a malpractice reflex. They are not anti-AI; they are
  anti-vendor-who-doesn't-get-my-operation. **Insight builds trust faster than
  any capability claim.**
- **Constantly fighting turnover and inconsistency.** Scaling means perpetual
  churn; "each file moves differently depending on who's running it" — a *systems*
  problem, not a personnel one. Owners want the firm to run without depending on
  any one heroic paralegal.

### What this means for the wedge
Lead with **Pain → new tech → ROI, in the owner's native units**: signed cases,
cost per case, cycle time to the settlement check, paralegal hours reclaimed,
turned-away cases. Never lead with "AI." Show them a number about their own firm
they didn't have, and make the bad news specific.

---

## Pain-point map (ranked by acuteness × our ability to make it firm-specific from outside)

| # | Pain cluster | Why it hurts (research) | Externally observable? | Maps to PM build |
|---|---|---|---|---|
| 1 | **Speed-to-lead / missed & after-hours calls** | LSA penalizes missed calls (lower rank); slow callback spikes acquisition cost; lost first call = lost ~$tens-of-thousands case | **Yes** — testable directly | Voice intake (already built for Precise) |
| 2 | **Intake conversion** | ~8% intake→retainer is common; reputation 4.7 vs 4.0 = +25–30% conversion; 80% of complaints are client-experience | **Yes** — website/forms/reviews public | Chatbot, intake voice |
| 3 | **Medical-records / case-prep bottleneck** | 56% of PI pros want AI for records summary; 15–25 hrs/case (80+ complex); firms turn away viable cases | Partially (volume estimable) | Records/demand automation |
| 4 | **Demand-letter throughput** | 60–70% time reduction reported with AI; biggest measurable ROI area | No (internal) | Demand automation |
| 5 | **Reputation / reviews** | GBP is #1 ranking factor; review velocity drives conversion | **Yes** — public | Review/feedback automation |
| 6 | **Lien resolution / disbursement delay** | 30+ day delays common; Medicare 6–12 mo; bottleneck delays the check & frustrates clients | No (internal) | Lien-resolution accelerator |
| 7 | **AI governance / malpractice exposure** | 44% no policy; bar rules + sanctions risk | Self-report only | Readiness/advisory |
| 8 | **Staff turnover / workflow inconsistency** | Files move differently per person; onboarding drag | No (internal) | Ops standardization |

Clusters 1, 2, 5 are externally observable → strongest freeware candidates.
Clusters 3, 4, 6, 7, 8 are internal → best served by self-assessment tools
(aiaudit-style) or as the *paid* expansion the free tool leads into.

---

## Existing portfolio (recap)

- **aiscan — AI Search Visibility** (external client-acquisition gap).
- **aiaudit — AI Readiness Audit** (internal operational-readiness gap).

The pain map shows the obvious whitespace: the two existing tools cover "AI
search visibility" and "internal readiness," but **not the firm's #1 measurable
revenue leak — the intake funnel itself.** That is where the next tools go.

---

## Freeware idea backlog (ranked)

Each idea is scored against the seven franchise rules in
`FREEWARE_GTM_STRATEGY.md`. "Conviction" weights acuteness, defensibility, how
verifiable/firm-specific the finding is, and fit with what PM can actually build.

### TIER A — build next

#### A1. Ghost Lead Test — speed-to-lead & after-hours intake leak report  ★ highest conviction
**The question:** "When a real injury victim calls or messages your firm after
hours, what actually happens?"
**How:** With consent-safe methodology, run a standardized intake probe against
the firm's *public* channels — measure web-form auto-response time, click-to-call
presence on mobile, after-hours handling (live vs voicemail vs dropped), Spanish
path, and callback latency. Report: "We submitted a test inquiry at 7:42pm
Tuesday; no response in 18 hours. Two local competitors replied within the hour."
**Why it wins:** Hits the #1 documented, owner-obsessed revenue leak; the finding
is brutally verifiable and self-evidently true; "bad news is a feature" by
construction; maps directly onto PM's existing voice-intake product as the
expansion. This is the single best fit between an acute pain and our build.
**Ladder:** free leak report → continuous mystery-shopping monitoring → after-
hours / overflow voice-intake build (the welcomed wedge per the intake research:
the alternative to a bot after hours is voicemail, not a human).
**Risk/ethics flag (resolve before build):** probing real firms touches their
staff/systems. Define a non-deceptive, low-burden methodology (e.g., identifiable
test inquiry, single touch, rate-limited) and a kill criterion; do **not** tie up
live intake staff or impersonate a real claimant. This is the one idea where the
HOW carries reputational risk — get it right or don't ship it.

#### A2. Intake Conversion Teardown — website & funnel friction report
**The question:** "How many signed cases is your website quietly costing you?"
**How:** Crawl the firm's public site + GBP: mobile click-to-call, form length &
fields, live chat presence, after-hours messaging, page speed, Spanish-language
intake, trust/proof elements, review rating & velocity. Score the funnel and tie
each gap to estimated conversion/cost-per-case impact in the owner's units.
**Why it wins:** Fully public (clean batch pre-generation), verifiable, defensible
(no overclaim), and lands in the cost-per-case frame the owner already lives in.
Natural sibling to aiscan (shares the crawler + "send to your web team" work
order) but aimed at conversion, not AI visibility.
**Ladder:** free teardown → conversion monitoring → chatbot / intake build.

### TIER B — strong, build after A or bundle

#### B1. Reputation & Review Scorecard
**The question:** "Is your reputation winning or losing you cases vs. the firm
across town?" Public Google rating, review velocity, unanswered-review rate,
sentiment themes, competitor comparison; tie to the 4.7-vs-4.0 = +25–30%
conversion finding.
**Caveat:** more commoditized (many reputation vendors). Best shipped as a
**component of a composite report** rather than a standalone hero tool, and
differentiated by linking review content to AI-search citations (aiscan overlap).

#### B2. Case-Prep Burden Calculator
**The question:** "How many paralegal hours and how much settlement delay is your
records/demand process costing you?" Inputs: case volume (estimable from staff
count / ad spend), case mix. Output: estimated hours sunk in records review +
demand prep, cycle-time-to-check impact, and turned-away-case cost — benchmarked
against the 15–25 hrs/case and 60–70% AI-reduction figures.
**Caveat:** calculator, not a scan — less verifiable/firm-specific, so weaker as a
cold hero hook. Strong as a **follow-on inside aiaudit** or a demand/records
expansion pitch once a conversation exists.

### TIER C — submodules / later

- **C1. AI Malpractice-Risk Check** — fold into **aiaudit** as a dimension
  (governance policy, public-tool confidentiality exposure, verification
  workflow). Sharp fear hook (44% no policy; sanctions risk) but self-report only,
  so it's a readiness-survey question, not its own scan.
- **C2. Competitor Composite Report** — the *aggregation layer*: once 2–3 scanners
  exist (aiscan + A2 + B1), bundle them into one metro competitive teardown.
  Leverages the champion/keeping-up dynamic; build it only after the components
  prove out.

---

## Recommended sequencing

1. **A1 Ghost Lead Test** — highest pain-to-build fit; resolve the methodology/
   ethics question first, then ship.
2. **A2 Intake Conversion Teardown** — reuses the aiscan crawler; fast to stand up.
3. Bundle **B1** into the A2 report (reputation is a conversion factor).
4. **C2 Composite** once A2 + B1 + aiscan share one report surface.
5. **B2 / C1** as expansion-stage assets, not cold hero tools.

Every one of these must inherit the franchise rules (insight-led, defensible,
bad-news-is-a-feature, batch pre-generation, CLI-first, launch gate + kill
criterion, free→monitoring→execution). New ideas get added here first, promoted
to their own spec only when they pass the bar.

---

## Sources (research 2026-06-21)

- Case-prep / records bottleneck & inconsistency: NexLaw, CasePeer, Tavrn, CloudLex.
- Cost per case / ad spend: iMark, Legal Leads Group, iLawyer Marketing, Dot Com Media, NatLawReview.
- AI adoption / records / demand letters: ABA Law Technology Today, Tavrn, LawPractice.ai, Inquery.ai, Quilia.
- Lien / disbursement delay: Bell Law, Wagstaff, Attorney at Law Magazine, Munley.
- Owner mindset / scaling / turnover: Attorney at Work (Morgan), RunSensible, Trial Guides, Financial Models Lab.
- Reputation / speed-to-lead / missed calls: Case Status, JurisGrowth, EmbedMyReviews, 12AM Agency.
- AI governance / malpractice / bar rules: NC Bar, Clio, ABA (Formal Op. 512), Thomson Reuters, Spellbook.
</content>
