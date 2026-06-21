# AI Search Visibility Tool Spec (v2)

> **v2 changelog — improvements folded in (2026-06-17).** This revision keeps the
> original strategy intact and resolves the open questions plus three trust
> risks that the v1 draft had scheduled as *post-launch validation*. The
> material changes, all authoritative for implementation:
>
> 1. **Delivery model: pre-generate reports for named outbound targets.** The
>    default path is a batch job that scans a firm *before* the email is sent;
>    the email carries one verifiable finding and links to a finished report. We
>    do not make known leads click a tool to start a scan. (Resolves the
>    cost/latency risk and the "one finding vs. link" open question.)
> 2. **Variance is a launch gate, not a later feature.** Run **3 runs per
>    high-weight query in V1** and report presence as "appeared in N of 3."
>    Suppress any competitor seen only once from the headline.
> 3. **Competitor normalization gets a human-review queue that gates outbound**
>    for the first batches. A directory or lead-gen site mis-tagged as a law
>    firm, or a dedup miss, discredits the whole report.
> 4. **Report UX leads with one verifiable verdict line and a named competitor**,
>    elevates "AI is describing your firm incorrectly" to its own callout, and
>    produces a copy-pasteable **"send to your web team" work order** per
>    recommendation. The 100-point score is kept but de-emphasized behind
>    verifiable counts.
> 5. **Calibration before outbound + an explicit kill criterion.** Manual
>    baseline runs before the first outbound batch; if <50% of the first 50
>    reports yield a competitor list the owner recognizes, halt outbound and fix
>    extraction.
> 6. **`web_search` scans call OpenAI directly**, never through the
>    `openclaw/proxy` gateway (the gateway is for the cheap text LLM tasks).
>
> Each change is detailed in its section below and is reflected in *MVP scope*.

## Purpose

Build a free web tool for personal injury firm owners to check whether their
firm shows up when potential clients ask ChatGPT-style search questions such as
"car accident lawyer near me," "accident lawyer in Los Angeles," "best personal
injury attorney for a truck accident in Dallas," or "who should I call after a
rideshare accident in Atlanta?"

This is part of the freeware strategy for Possible Minds: send prospects a
specific, useful diagnostic link in outbound email and LinkedIn messages. The
tool should give the owner a reason to click even if they are tired of AI demos:
it does not ask them to watch a pitch; it shows whether their firm is visible in
an emerging client-acquisition channel, which competitors are appearing instead,
and what can be fixed on their website to improve the odds that AI search
systems understand and recommend them.

The wedge is not "we built an AI tool." The wedge is: "When someone in your city
asks an AI assistant who to call after a crash, are you in the answer?"

## Strategic context

PI firm owners already understand Google rankings, local pack placement, reviews,
and referral reputation. AI search is newer and harder for them to inspect. That
gap creates a compelling freeware product because it turns an abstract platform
shift into a concrete, firm-specific report:

- "You appeared in 2 of 18 high-intent AI search checks."
- "Three local competitors appeared more often than you."
- "Your site is not making your core practice areas, service area, attorney
  credentials, and proof points easy for answer engines to cite."
- "Here are the five website changes most likely to improve your visibility."

The tool should feel like a sharp market diagnostic, not a generic website audit.
The report must compare the firm against recognizable competitors, show example
AI answers, and prioritize fixes in plain business language.

## Feasibility and constraints

OpenAI's current API surface supports a practical version of this product through
the Responses API and hosted `web_search` tool. The API can run standardized
queries, use web search, return answers with URL citations, and accept approximate
user location context for local relevance. OpenAI recommends the Responses API
for new projects and lists built-in web search as one of its tools.

Sources checked:

- OpenAI web search guide: https://developers.openai.com/api/docs/guides/tools-web-search
- OpenAI Responses API migration guide: https://developers.openai.com/api/docs/guides/migrate-to-responses

The hard constraint: this tool should not claim to be an official consumer
ChatGPT ranking report. Consumer ChatGPT results can vary by time, model,
location, personalization, account context, search freshness, and presentation.
The correct claim is narrower and more defensible:

"We run standardized AI search checks for your market and measure whether your
firm appears, how prominently it appears, which competitors appear instead, and
which web sources the answer uses."

Owner-facing language should avoid technical implementation terms. Say "AI search
checks," "AI answer visibility," "sources," "competitor visibility," and "website
changes." Avoid saying "LLM," "prompt," "web crawler," "inference," or "model
gateway" in prospect-facing screens.

## What will be compelling to PI owners

PI owners will care if the report maps to client acquisition, not if it talks
about AI as a technology category. The strongest hooks are:

- Client-intent framing: "Would a potential client asking for help after a crash
  find you or your competitor?"
- Competitor anxiety: "These firms are showing up in answers where you are not."
- Local market specificity: city, county, and accident type matter more than a
  national score.
- Proof of work: show the actual query checks, answer excerpts, and cited
  sources so it does not feel like a black-box grade.
- Actionability: owners should leave with fixes they can hand to their web
  agency today.
- Retest loop: "Make these changes, then rerun the scan in 30 days."
- Freeware generosity: give enough value without forcing a call, then make the
  call feel like the natural next step for owners who want help executing.

The emotional posture should be diagnostic and direct. Many PI firms are tired
of AI demos. This tool should lead with a market fact about the firm, not a demo
of technology.

## Product surface

### Public route

Working route name: `/ai-visibility`

Alternative public names:

- `ChatGPT Visibility Check`
- `AI Search Visibility Report`
- `Personal Injury AI Visibility Audit`

For outbound, the route should support prefilled links:

`/ai-visibility?firm=<slug-or-id>&market=los-angeles-ca`

Prefilled links matter because the email can say:

"I ran a quick AI visibility check for [Firm]. It looks at whether you show up
when someone asks for a car accident lawyer in [City]."

### Input flow

The lowest-friction version should ask for:

- Firm name
- Website
- Primary city/market
- Main practice area focus, defaulting to auto accidents
- Optional email to receive the full report

If the prospect arrives from a known outbound lead, the form should be prefilled
and the primary action should be "Run visibility check."

Recommended gating (v2 — pre-generation changes this):

- **Named outbound targets (the primary path): the report is already generated.**
  A batch job scans the firm before the email goes out, so the prefilled link
  opens a finished report with zero wait and zero form. Do not email-gate this
  cohort — they have already identified themselves by being a known lead, and
  gating is friction against the best audience.
- **Cold organic visitors** (anonymous, arrived at `/ai-visibility` directly):
  show an instant headline preview, then gate the full report behind an email.
  Live on-demand scans for this cohort run as background jobs with a hard daily
  cap (cost/abuse control).
- Require email only for: cold-visitor full reports, saved history, or retest
  reminders. Never for an outbound prospect's own prefilled link.

### Result dashboard

The result page should have a single hero line above the fold, then seven
sections.

**Hero (above the fold, v2):** one verifiable verdict sentence the owner could
read aloud to a partner, plus the single most threatening named competitor.
Example: *"In June 2026, your firm appeared in 2 of 12 high-intent accident
searches in Los Angeles. The Barnes Firm appeared in 9."* The hero leads with
verifiable counts and a real competitor name — not the 100-point score.

1. Visibility score
   - Three **verifiable** headline counts first: appeared in N of M checks;
     competitors that beat you; facts AI got wrong about you.
   - Overall score out of 100, shown but de-emphasized (a composite invites the
     "feels arbitrary" reaction; verifiable counts do not).
   - Plain-language verdict, e.g. "Low visibility in high-intent local accident
     searches."

2. Competitor comparison
   - Table of firms found in the same AI answers.
   - Columns: firm, appearances, highest position, cited source count, query
     categories where they appeared.
   - Highlight "firms appearing where you did not."
   - **Name *why* a competitor won (v2):** for each query the firm lost, point at
     the specific competitor page the answer cited and the reason it won (e.g.
     "one page combining city + practice area + attorney proof + reviews"). The
     causal link — not just the absence — is what turns the report into a
     meeting.
   - One-click feedback per row: "this competitor isn't relevant." Feeds
     normalization and creates a sales-follow-up hook.

3. Query matrix
   - Rows are client-search scenarios.
   - Columns: query, your firm result, competitor result, cited sources, answer
     confidence, timestamp.
   - Categories:
     - General local PI: "personal injury lawyer near me"
     - Auto accident: "car accident lawyer in {city}"
     - Truck accident
     - Motorcycle accident
     - Rideshare accident
     - Pedestrian/bicycle accident
     - Spanish-language query in relevant markets
     - Urgent after-hours query
     - Comparative query: "best accident lawyer in {city}"
     - Proof query: "lawyer with big car accident settlements in {city}"

4. Answer evidence
   - Show short excerpts from representative AI answers.
   - Show source URLs that were cited.
   - Label when the firm was absent, mentioned, recommended, or cited.
   - Keep excerpts short; link to stored observation detail internally.

5. How AI is describing your firm (accuracy callout, v2)
   - A dedicated box surfacing wrong or missing facts: "AI said you don't handle
     truck accidents — you do," "AI listed the wrong office city," "AI could not
     find your attorneys."
   - This is more alarming and more credible than any score because the owner can
     instantly verify it is true. Drawn from `accuracy_flags_json`.
   - One-click "this fact is wrong / this is actually correct" feedback per item.

6. Website action plan
   - Top 5 recommended changes, ranked by likely visibility impact.
   - Each recommendation ties to evidence from the scan or website analysis.
   - **Each recommendation ships a "send to your web team" work order (v2):** a
     copy-pasteable brief with the target URL, a page outline, the exact facts to
     include (attorney names, recoveries, service area), and the schema type. PI
     owners don't build pages — their agency does; the product's job is to
     generate the work order, not just the diagnosis. (This also pre-builds the
     V4 execution product.)
   - Example:
     - "Create a dedicated Los Angeles car accident page with attorney names,
       recoveries, reviews, process, and FAQs."
     - "Make attorney credentials and trial experience easier to find from your
       home page."
     - "Add structured FAQ content for high-intent accident questions."
     - "Consolidate inconsistent practice-area language across key pages."
     - "Add clear source-worthy proof: case results, client reviews, awards, and
       office/service-area details."

7. Next step CTA
   - Primary CTA: "Get a prioritized visibility plan."
   - Secondary CTA: "Retest after website updates" — the report URL re-runs the
     scan after 30 days and shows a before/after delta, turning the diagnostic
     into a scheduled second conversation.
   - Tertiary: "Send this report to my web team" (the shareable URL is the viral
     loop — every forward to an agency is a warm third-party intro).
   - Do not lead with "book an AI demo."

## Scoring model

The score should be explainable. Avoid a mysterious vanity grade.

### Core metrics

- Presence rate: percentage of query checks where the firm appears at all.
- Prominence: how early and strongly the firm appears in the answer.
- Recommendation strength: whether the answer merely mentions the firm or
  positions it as a good option.
- Citation strength: whether the firm website or authoritative third-party pages
  are cited.
- Competitive share of answer: how often competitors appear relative to the
  firm.
- Accuracy: whether the answer describes the firm's market, practice areas,
  attorneys, and office locations correctly.
- Source quality: whether the answer relies on useful sources such as the firm
  website, Google Business Profile-like information, legal directories, reviews,
  news, awards, or authoritative local pages.

### Suggested weighting

- 35% presence and prominence across high-intent queries
- 20% competitor share of answer
- 15% citation strength
- 15% answer accuracy
- 15% website readiness signals

### Query weighting

Not all queries are equal. Weight high-commercial-intent local auto accident
queries more heavily than broad educational questions.

Example weights:

- "car accident lawyer in {city}" = high
- "personal injury lawyer near me" = high
- "truck accident lawyer in {city}" = medium/high
- "what to do after a car accident in {city}" = medium
- "best accident lawyer in {city}" = medium, because "best" answers are often
  volatile and reputation-source-dependent
- "how long do I have to sue after an accident" = low for firm visibility,
  useful for content advice

## Competitor detection

The clean competitor list should combine observed AI answer competitors with
existing lead-gen intelligence.

Priority order:

1. Observed competitors from the scan
   - Any law firm that appears in the same AI answer set for the prospect's
     market and practice area.
   - Extract firm name, website, city, answer position, source URLs, and query
     category.

2. Existing Possible OS competitor graph
   - Use the current PI firm competitor graph as a seed list when a known firm
     has already been mapped.
   - This improves consistency and reduces one-off naming drift.

3. Search/local-market candidates
   - If the scan finds too few competitors, supplement from local search result
     sources or directory pages that appear in answer citations.

4. Owner-supplied competitors
   - Let the firm add competitors they care about, but keep those separate from
     "observed in AI answers" so the report remains evidence-backed.

Normalize names aggressively:

- Canonical firm name
- Common aliases
- Website domain
- Market
- Practice-area overlap
- Confidence score

The owner-facing list should be clean and stable. Do not show duplicate variants
like "The Barnes Firm" and "Barnes Firm" as separate competitors.

## Website recommendation engine

The advice layer should not be generic SEO filler. It should combine scan
evidence with website analysis.

### Inputs

- Firm website pages:
  - Home page
  - Primary practice area pages
  - City/location pages
  - Attorney bio pages
  - Results/testimonials pages
  - FAQ/blog pages
- Scan observations:
  - Queries where firm was absent
  - Queries where competitors appeared
  - Sources cited by AI answers
  - Descriptions or facts used in answers
  - Missing or wrong facts
- Competitor pages:
  - Pages that were cited or appear to support competitor visibility

### Recommendation categories

1. Entity clarity
   - Firm name, location, attorneys, service area, and practice areas must be
     easy to identify.

2. Local relevance
   - City and county pages should be specific, useful, and tied to real office
     presence or service-area details.

3. Practice-area depth
   - Dedicated pages for auto, truck, motorcycle, rideshare, pedestrian, and
     wrongful death when relevant.

4. Proof and trust
   - Attorney credentials, case results, reviews, awards, associations, media,
     and client process.

5. Answer-ready content
   - Directly answer high-intent questions potential clients ask before calling.

6. Structured data and technical basics
   - Organization, LocalBusiness/LegalService, attorney/person, FAQ, breadcrumb,
     reviews where appropriate, canonical pages, crawlable navigation,
     page speed, mobile usability, and indexability.

7. Source ecosystem
   - Strengthen third-party profiles and pages that AI answers commonly cite:
     legal directories, review sites, local listings, awards pages, podcast/news
     appearances, and high-authority local references.

8. Reputation consistency
   - Ensure name, address, phone, practice focus, and service-area claims are
     consistent across the web.

### Recommendation format

Each recommendation should include:

- Title
- Why it matters
- Evidence from this scan
- Exact pages affected
- Suggested change
- Effort level
- Expected impact
- Optional example copy or page outline

Example:

```text
Add a dedicated Los Angeles car accident page

Why it matters:
Your firm was absent from 5 of 6 auto-accident queries, while two competitors
were cited from pages that clearly combine "Los Angeles," "car accident," attorney
credentials, and client proof.

Suggested change:
Create a page focused on Los Angeles car accident cases with attorney bios,
recent recoveries, FAQs, office/service-area details, and a clear intake CTA.

Effort: Medium
Expected impact: High
```

## Internal architecture

### Primary objects

`visibility_scans`

- `id`
- `firm_id` nullable, when linked to an existing lead-gen firm
- `firm_name`
- `firm_domain`
- `market_city`
- `market_region`
- `practice_focus`
- `status`
- `requested_by_email`
- `source` (`outbound_email`, `linkedin`, `manual`, `internal`)
- `created_at`
- `completed_at`
- `model_provider`
- `model_name`
- `search_tool_name`
- `location_context`
- `overall_score`
- `summary_json`

`visibility_queries`

- `id`
- `scan_id`
- `query_text`
- `query_category`
- `weight`
- `location_context`
- `status`
- `created_at`
- `completed_at`

`visibility_observations`

- `id`
- `query_id`
- `raw_response_json`
- `answer_text`
- `source_urls_json`
- `mentioned_firms_json`
- `target_firm_presence`
- `target_firm_position`
- `target_firm_cited`
- `competitor_mentions_json`
- `accuracy_flags_json`
- `created_at`

`visibility_competitors`

- `id`
- `scan_id`
- `canonical_name`
- `domain`
- `market`
- `appearance_count`
- `best_position`
- `cited_source_count`
- `evidence_json`
- `source` (`observed`, `competitor_graph`, `owner_supplied`, `supplemental`)
- `confidence`

`visibility_recommendations`

- `id`
- `scan_id`
- `category`
- `title`
- `why_it_matters`
- `evidence_json`
- `affected_pages_json`
- `suggested_change`
- `effort`
- `expected_impact`
- `priority`
- `work_order_json` (v2) — copy-pasteable web-team brief: target URL, page
  outline, required facts, schema type

`visibility_feedback` (v2)

- `id`
- `scan_id`
- `target_type` (`competitor`, `accuracy_flag`, `recommendation`)
- `target_id`
- `verdict` (`not_relevant`, `wrong`, `correct`, `already_have_it`)
- `note`
- `created_at`

Owner feedback feeds normalization and competitor-graph cleanup, and each
submission is a sales-follow-up signal. The aggregated per-query run counts
(N-of-3 presence) live in `visibility_queries.summary` / are derived from the
multiple `visibility_observations` rows per query — no separate table.

### Services

> **Provider note (v2):** two LLM paths, kept separate.
> - `AiSearchCheckRunner` calls **OpenAI directly** (its own `OPENAI_API_KEY`)
>   via the **Responses API** with the hosted `web_search` tool. Web search is an
>   OpenAI hosted tool — the OpenClaw gateway is chat-completions only and cannot
>   run it, and a plain text model would fabricate answers rather than measure
>   real AI search. This path is never proxied.
> - The cheaper **text tasks** (competitor + accuracy extraction, `is_law_firm`
>   edge cases, recommendation/work-order phrasing) default to the **OpenClaw
>   gateway** (`openclaw/proxy`, the `call_skill_json` pattern shared with the
>   possibleos email composer / lead-feedback classifier), with a direct-OpenAI
>   fallback. Backend selected via `LLM_TEXT_BACKEND` (`gateway`|`openai`). These
>   stay isolated from the web-search path.


`VisibilityScanService`

- Creates scans.
- Builds query set from market and practice focus.
- Dispatches query jobs.
- Aggregates observations into scores.

`AiSearchCheckRunner`

- Calls OpenAI Responses API with web search.
- Supplies location context when possible.
- Stores raw response metadata, citations, and answer text.
- Uses structured extraction to identify firm mentions, citations, and
  competitor names.

`CompetitorNormalizer`

- Deduplicates law firm names.
- Maps observed names to existing firm records/domains where possible.
- Merges observed competitors with the existing competitor graph.
- **(v2) `is_law_firm` classifier + operator review queue.** Filters out
  directories (Avvo, FindLaw, Forbes "best of"), review sites, and lead-gen
  aggregators that get mistaken for law firms; collapses alias variants ("The
  Barnes Firm" / "Barnes Firm"). For the first batches, the normalized list is
  **held for operator approval before any report is sent** (see kill criterion in
  the accuracy plan). Exposed via CLI `aivis competitors --review <scan_id>`.

`WebsiteVisibilityAnalyzer`

- Fetches selected firm website pages.
- Extracts entity, local, proof, practice-area, structured-data, and content
  readiness signals.
- Compares gaps against competitor pages that appeared in answer citations.

`VisibilityRecommendationService`

- Converts evidence into owner-friendly recommendations.
- Ranks recommendations by impact and effort.
- Avoids generic suggestions that are not tied to scan evidence.

### CLI parity

Every backend capability must have a CLI command — the CLI is the operator
contract and the scriptable surface for batch pre-generation. Binary: `bin/aivis`.

```bash
bin/aivis scan \
  --firm-name "Example Injury Law" \
  --domain exampleinjurylaw.com \
  --market "Los Angeles, CA" \
  --practice auto-accident

bin/aivis show <scan_id>
bin/aivis competitors <scan_id>
bin/aivis competitors --review <scan_id>      # approve/reject normalized list
bin/aivis recommendations <scan_id>
bin/aivis rerun <scan_id>
bin/aivis batch --from <leads.csv>            # pre-generate reports for outbound
bin/aivis report-url <scan_id>                # shareable public URL
```

## API sketch

Public web app endpoints:

- `GET /ai-visibility`
- `POST /api/ai-visibility/scans`
- `GET /api/ai-visibility/scans/{scan_id}`
- `GET /api/ai-visibility/scans/{scan_id}/report`
- `POST /api/ai-visibility/scans/{scan_id}/email-report`

Internal/operator endpoints:

- `GET /api/visibility/scans`
- `GET /api/visibility/scans/{scan_id}/raw`
- `POST /api/visibility/scans/{scan_id}/rerun`
- `POST /api/visibility/scans/{scan_id}/review` — approve/reject normalized
  competitor list (gates outbound for early batches)
- `POST /api/visibility/batch` — pre-generate scans for a list of outbound leads
- `POST /api/ai-visibility/scans/{scan_id}/feedback` — owner feedback (competitor
  not relevant / fact wrong / already have page)

## Scan design

### MVP query pack

Run 12 to 20 checks per firm. That is enough to produce a useful report without
making the free tool expensive or slow.

Recommended default pack:

1. "car accident lawyer in {city}"
2. "best car accident lawyer in {city}"
3. "personal injury lawyer near me" with location context
4. "accident attorney in {city}"
5. "truck accident lawyer in {city}"
6. "motorcycle accident lawyer in {city}"
7. "pedestrian accident lawyer in {city}"
8. "rideshare accident lawyer in {city}"
9. "lawyer after a hit and run in {city}"
10. "who should I call after a car accident in {city}"
11. "personal injury lawyer with strong reviews in {city}"
12. "lawyer for serious injury accident in {county}"

Optional additions:

- Spanish-language queries in relevant markets.
- "near me" variants with precise location hints.
- Brand-specific query: "Is {firm_name} a good car accident law firm?"
- Competitor-comparison query: "{firm_name} vs {competitor_name}"

### Repeated runs (v2 — variance is a launch gate)

AI answers vary, and a free report that shows different competitors on different
days destroys the trust the whole product depends on. The v1 "run each query
once" plan is the cheapest path to that failure, so v2 changes the MVP:

- **V1: 3 runs per high-weight query** (medium/low-weight queries may run once to
  cap cost). Report presence as "appeared in N of 3 checks." Suppress any
  competitor seen in only one of three runs from the headline and competitor
  table (keep it in raw observation detail). `visibility_observations` already
  stores one row per run, so this needs no schema change — just multiple
  observation rows per query and aggregation logic.
- Always stamp the report with run count, timestamp, and "point-in-time
  diagnostic" so the "I just tried it and saw something else" objection is
  pre-empted honestly.

For paid/internal use, extend to:

- 3 runs per query on different days (not just same-session)
- trend view by week/month
- confidence intervals for presence/prominence
- alerts when a competitor starts appearing more often

## Accuracy validation plan

Validation matters because owners will distrust a report that feels arbitrary.

0. Kill criterion (v2 — gates scaling)
   - If fewer than ~50% of the first 50 reports produce a competitor list the
     owner recognizes (via the in-report feedback widget + sales-call
     validation), the scan evidence is not trustworthy enough to scale — **halt
     outbound and fix extraction** before sending more. The product lives or dies
     on whether owners recognize the competitors.

1. Manual baseline (v2 — runs BEFORE the first outbound batch, not in parallel)
   - For 20 sample firms across 5 markets, manually run the same queries in
     consumer ChatGPT search and compare the firms/sources that appear.
   - Use this to calibrate query wording, scoring, and disclaimers — and to
     measure how well the `web_search` tool's results correlate with what a
     consumer actually sees, since a savvy owner may open ChatGPT on the call.
   - Calibrate report copy to whatever actually correlates; keep the public claim
     narrow ("standardized AI search checks").

2. Repeatability check
   - Rerun the same scan multiple times across several days.
   - Track variance in presence, source URLs, and competitor names.
   - Use variance to decide whether a query category should be weighted lower.

3. Source verification
   - Every recommendation should cite scan evidence or website evidence.
   - Reject recommendations that cannot be traced back to an observed gap.

4. Competitor normalization review
   - Audit extracted competitor names for duplicates, non-PI firms, directories,
     and lead-gen sites incorrectly treated as law firms.

5. Website-analysis sanity checks
   - Compare extracted facts against the firm's website.
   - Flag uncertainty instead of making strong claims when pages are blocked,
     thin, or ambiguous.

6. Owner feedback loop
   - Let owners mark "this competitor is not relevant," "this fact is wrong," or
     "we already have this page."
   - Feed corrections into future scans and competitor graph cleanup.

7. Sales-call validation
   - In discovery calls, ask owners whether the competitor list feels right and
     whether the top recommendations match what they know about their market.
   - Track which recommendations create real sales conversations.

## Owner-facing copy examples

Landing page headline:

"See whether your firm shows up when potential clients ask AI search for an
accident lawyer in your city."

Subcopy:

"Run a quick visibility check across high-intent accident-lawyer searches. See
which competitors appear, which sources are being used, and what to fix on your
site."

Result verdict examples:

- "Your firm is visible in branded searches, but mostly absent from high-intent
  local accident searches."
- "Competitors are being cited from pages that clearly connect city, practice
  area, attorney proof, and client reviews."
- "Your website has strong proof, but it is not organized in a way AI search can
  easily use for local accident-lawyer answers."

CTA examples:

- "Get a prioritized visibility plan"
- "Send this report to my website team"
- "Retest after updates"

Avoid:

- "Improve your LLM rankings"
- "Hack ChatGPT"
- "Guaranteed ChatGPT placement"
- "AI SEO secrets"

## Freeware and outbound strategy

### Use in cold email

The tool should support personalized links generated by the lead-gen system.
Each link should prefill the firm and market, and ideally attach known competitor
context.

Outbound angle:

"I was checking whether PI firms show up when people ask AI search for accident
lawyers in their city. I made a quick report for [Firm] in [City]. It shows
which competitors appear and the website changes that would likely help."

This is stronger than asking for a demo because it gives the recipient a
firm-specific reason to click.

### Use in LinkedIn

LinkedIn messages should be shorter and curiosity-driven:

"I put together a quick AI visibility check for [Firm] in [City] - whether you
show up when someone asks for a car accident lawyer nearby, and who appears
instead. Want me to send it?"

If sending a direct link is acceptable:

"This is the report: [link]. The useful part is the competitor comparison."

### Follow-up strategy

The report gives natural follow-up hooks:

- "Did the competitor list look right?"
- "The biggest gap was [specific gap]."
- "Your reviews are strong, but the site does not make [practice/market] easy to
  cite."
- "Worth rerunning after your next website update."

## MVP scope

### Build first

- CLI-first scan loop (`bin/aivis scan/show/competitors/recommendations`) — the
  scan evidence must be trustworthy before any dashboard is polished.
- **Batch pre-generation** (`bin/aivis batch`) for named outbound leads — the
  primary delivery path; reports are ready before the email is sent.
- Scan runner with 12 to 20 standardized queries; **3 runs per high-weight
  query** with N-of-3 presence aggregation (variance gate).
- OpenAI **Responses API web search, called directly** (own key, not via gateway).
- Observation extraction for: target firm presence, competitor mentions, source
  URLs, answer excerpt, **accuracy flags** (wrong/missing facts).
- `CompetitorNormalizer` with `is_law_firm` filter + dedup + **operator review
  queue** that gates outbound for early batches.
- Clean competitor table that **names why each competitor won**.
- Three verifiable headline counts + de-emphasized 100-point score.
- "How AI is describing your firm" accuracy callout.
- Website analyzer for home page plus top discovered practice/location pages.
- Top 5 recommendations, **each with a "send to your web team" work order**.
- Shareable report URL (forward-optimized: OG card, "prepared for {Firm}").
- In-report feedback widget (competitor / fact / recommendation).
- Public `/ai-visibility` page with prefilled outbound links (no email gate for
  the known-lead cohort).

### Defer

- Full PDF export.
- Multi-provider comparison across ChatGPT, Perplexity, Gemini, and Google AI
  Overviews.
- Daily/weekly monitoring.
- Owner login and account history.
- Automated website-change implementation.
- Paid retest plans.
- Deep backlink/citation graph.

## Later roadmap

### Version 1: Free diagnostic

- One-off scans.
- Email capture for full report.
- Outbound prefilled links.
- Basic competitor comparison.
- Action plan.

### Version 2: Monitoring

- Monthly retests.
- Trend lines.
- Alerts when competitors overtake the firm.
- "Before/after" view after website changes.

### Version 3: Multi-engine visibility

- Compare ChatGPT-style search, Perplexity, Gemini, Google AI Overviews, and
  classic Google local/search.
- Show which fixes overlap across channels and which are channel-specific.

### Version 4: Execution product

- Turn recommendations into website tickets.
- Generate draft page outlines and copy blocks.
- Integrate with the firm's web vendor or CMS.
- Track implementation and retest results.

## Risks

- Overclaiming: the tool must not imply official ChatGPT ranking access.
- Volatility: point-in-time answers may change.
- Cost: free scans need query caps, caching, and abuse controls. **Set a
  per-scan budget before building** (≈ high-weight queries × 3 runs × web-search
  cost + extraction + ~6 page fetches). Control it by pre-generating only for
  firms you actually email and hard-capping live cold-visitor scans per day.
- Latency: a 20-query live scan may be too slow for a public page; use background
  jobs and progressive result loading.
- Accuracy: competitor extraction needs normalization and human-review tools.
- Legal marketing sensitivity: recommendations must avoid fake reviews,
  misleading claims, keyword stuffing, or fabricated case results.
- Prospect trust: if the tool feels like a gimmick, it will reinforce AI-demo
  fatigue.

## Success metrics

- Link click rate from outbound email and LinkedIn.
- Scan-start rate.
- Scan-completion rate.
- Full-report email capture rate.
- Reply rate after report follow-up.
- Consult/booked-call rate.
- Percentage of reports with at least one meaningful competitor finding.
- Percentage of reports with at least one high-confidence website recommendation.
- Retest rate after 30 days.
- Owner feedback: "competitor list is accurate" and "recommendations are useful."

## Open questions

Resolved in v2:

- **Naming** → Use "AI Search Visibility" in the product, report, and any
  footer/legal copy (defensible). "ChatGPT-style search" is fine in conversational
  email body where it is not a formal claim.
- **Email-gating** → Do not gate the known-lead outbound cohort; gate only cold
  organic visitors. (See *Input flow*.)
- **Query count / cost** → 12–20 queries, but 3 runs only on high-weight queries;
  control cost via pre-generation for emailed firms + daily cap on cold scans.
- **One finding vs. link in email** → Put one verifiable finding (named
  competitor that beat them) in the email body; full report behind the link.
- **Single vs. multi provider** → MVP uses OpenAI web search only; multi-engine
  is V3. Use the manual ChatGPT baseline (not a second API) for V1 validation.

Still open:

- How much website analysis should run synchronously before the page feels slow?
  (Mitigated by pre-generation, but matters for cold live scans.)
- Exact disclaimer language for the report footer (point-in-time, standardized
  checks, not official ChatGPT ranking).
- Final per-scan dollar budget and the daily cold-scan cap number.

## Recommended first implementation slice

Build the smallest complete loop:

1. Operator runs a CLI scan for one known PI firm.
2. System runs 12 standardized AI search checks for one market.
3. System extracts target-firm presence, observed competitors, answer excerpts,
   and source URLs.
4. System analyzes the firm home page plus up to five relevant internal pages.
5. System generates a report with score, competitor table, query matrix, and top
   five recommendations.
6. Public report URL can be sent in an outbound email.
7. Sales follow-up captures whether the competitor list and recommendations were
   perceived as accurate.

Do not start with a polished dashboard before the scan evidence is trustworthy.
The product lives or dies on whether a PI owner recognizes the competitors and
believes the recommendations are specific to their firm.
