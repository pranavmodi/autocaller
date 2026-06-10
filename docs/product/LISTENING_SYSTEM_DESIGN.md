# PI Operator Listening System — design proposal

*2026-06-09. Goal: a recurring system that ingests what PI operators/thought leaders say (Reddit, Substack, podcasts, PILMMA & firm blogs, LinkedIn, …), compounds it into a living knowledge base of their mindset, and feeds outreach composition — without itself doing outreach.*

## The surprising starting point: you already built half of this

Mission Control already contains the capture layer, built and then left one-shot:

| Asset | State today |
|---|---|
| Reddit crawler (`reddit_posts`, `reddit_config`) | 756 posts from r/lawyers, r/LawFirm, r/LegalTech, r/plaintifflaw, r/Insurance +1; **last fetched 2026-03-11**; only 60/756 LLM-analyzed; 1 consolidation run |
| PILMMA research app (`research_posts`, `research_clusters`) | 384 blog posts crawled + analyzed; 14 pain-point clusters with emotional-charge ratings (intake/after-hours lead loss, AI-search visibility, staffing, settlement pressure…) — run twice, never refreshed |
| Podcast library (`pi_podcasts`, `pi_podcast_episodes`) | 46 PI podcasts, 3,060 episodes indexed, **250 transcribed** with formatted transcripts |
| Primary-contact tables | `customer_calls`, `front_messages`, `transcriptions` (21), `job_listings`, `linkedin_connections` (19) |

So this is not a green-field build. The gaps are: **(1) nothing recurs, (2) sources live in silos with per-source analysis formats, (3) there is no synthesis layer (the "mindset" asset), and (4) nothing bridges to the autocaller composer.** The design below closes those four gaps and adds the missing sources.

## Architecture

**Mission Control = listening hub** (capture + extraction + synthesis — it already has the crawlers, transcription, background-task pattern, and UI). **Autocaller = consumer** (composer and discovery-prep read the synthesized assets; CLI parity per the golden rule). Don't rebuild capture in autocaller; that duplicates 80% of working code.

```
SOURCES                INGEST (recurring)        CORPUS              EXTRACT (LLM)         SYNTHESIZE (weekly)        CONSUME
reddit_config       →  reddit poller          →                  →                      →                          →  autocaller composer
substack/RSS feeds  →  feed poller            →  listening_items →  listening_insights  →  mindset brief (vN)      →  discovery-prep briefs
podcast RSS         →  new-ep transcriber     →  (+ existing     →  typed, verbatim-    →  objection library       →  weekly digest email
PILMMA + firm blogs →  re-crawler             →   tables)        →  quote-first         →  vocabulary glossary     →  Alex call prompts
LinkedIn, calls     →  manual paste (CLI/UI)  →                  →                      →  persona notes
```

### 1) Make what exists recur (Phase 1 — highest ROI, mostly scheduling)

- **Reddit:** weekly scheduled crawl + auto-analyze of new posts (the endpoints exist: `/api/research/reddit/crawl`, `analyze-batch`). First action: analyze the 696 already-captured-but-unanalyzed posts.
- **PILMMA blog:** monthly re-crawl, incremental (skip known URLs).
- **Podcasts:** refresh feeds weekly; auto-transcribe new episodes of a shortlist matched to the 10 thought leaders from the strategy doc — Maximum Lawyer (Mutrux), Personal Injury Mastermind (Dreyer), Trial Lawyer Nation (Cowen), Elawvate (Gideon), LawDroid Manifesto (Martin). Don't transcribe all 46 shows; ~5 shows × ~1 ep/week is cheap and on-target.
- Scheduling: Mission Control has the background-task pattern; add a simple scheduler loop or systemd timers hitting its own API.

### 2) Add the missing sources (Phase 2)

- **Substack / blogs via RSS:** every Substack exposes `/feed`; most firm blogs have RSS or a sitemap. One generic `feed_sources` poller covers LawDroid Manifesto, Adam's Legal Newsletter, Daniel Roche's intake Substack, Legal Tech Trends, Rankings.io newsletter, and any PI firm blog you add. This is the cheapest new adapter.
- **LinkedIn:** be honest — no API, and scraping is ToS-risky and brittle. Make **manual paste a first-class channel** instead: a paste box in the UI + `listening add --source linkedin --author "Brian Glass" --paste` that runs the same extraction. Same channel handles discovery-call notes, conference hallway quotes, screenshots. (This matches the strategy doc's caution: the system *stores* understanding earned through primary contact; it can't scrape it.)
- **Their own artifacts:** `job_listings` already exists — three intake-hire postings = intake pain; wire it into extraction as a signal source. Glassdoor snippets via the paste channel.
- **Primary conversations:** pipe `customer_calls` / discovery-call transcriptions through the same extractor. These are the highest-signal items in the whole system — rank them above all scraped content.

### 3) Unified extraction → `listening_insights` (the layer that doesn't exist)

One normalized item table (`listening_items`: source, author, url, published_at, raw_text, content_hash) fed by all adapters, and one extraction pass (LLM-first, structured output, modeled on the yelp-review-quotes skill) producing typed, **verbatim-quote-first** insights:

`listening_insights(item_id, type, cluster, quote, paraphrase, who_feels_it, severity, confidence)`

Types: `pain_point | objection | vocabulary | belief | metric_they_trust | adoption_story | vendor_sentiment`. The `objection` and `vocabulary` types are what the current per-source analyses lack — reddit analysis captures pain points but not the *language* ("handoff repair," "another abstraction before it saves time") that makes an email sound like it was written by someone who's worked an intake desk.

### 4) Synthesis: the mindset brief (the asset you actually use)

A weekly job clusters new insights and regenerates a **versioned mindset brief** — one markdown artifact with: top clusters + trend deltas (rising/falling), objection-handling library, vocabulary glossary, persona notes (managing partner vs. intake manager vs. paralegal), and the 10-leader tracker (latest take per person). Version it like `lead_gen_policy_versions` so every outreach email can record which brief version informed it. Send a short weekly digest (operator notification) — that's your "get into their mindset regularly" loop even when you don't open the UI.

### 5) Consumption bridge to autocaller

- A read path (Mission Control API or sync, like `leads sync-mission`) so the composer can pull: current brief + top-k insights matched to the firm's ICP signals (e.g. ad-spend-heavy firm → intake-overflow quotes).
- CLI (golden rule): `listening brief show`, `listening search "intake"`, `listening quotes --cluster after-hours --limit 5`, `listening sync`.
- Second consumer: a **discovery-prep brief** generator ("about to call firm X — here's their likely persona, the objections to expect, the vocabulary to use"), which serves the conversations the doc says matter most.

## Build order

1. **Week 1:** analyze the 696 backlogged Reddit posts; schedule weekly Reddit + monthly PILMMA refresh; shortlist + auto-transcribe the 5 podcasts. *(No new schema — just makes existing assets current and recurring.)*
2. **Week 2:** generic RSS/Substack poller + manual-paste channel; `listening_items`/`listening_insights` schema + unified extractor; backfill extractor over existing reddit analyses, research posts, and the 250 podcast transcripts.
3. **Week 3:** weekly synthesis job → versioned mindset brief + digest email; autocaller `listening` CLI group + composer integration.

## User experience

The defining property: **you don't visit the system; it visits you, and it
never arrives without evidence and a suggested action.** Weekly attention cost
is ~10 minutes plus a couple of 2-minute alerts.

**Monday morning — the digest.** One email: "Mindset Brief v12 — what
changed." Three rising clusters with trend arrows, two verbatim quotes worth
reading in full, one proposed new voice ("J. Rivera, intake consultant, quoted
3× this month — track her?"), one health line ("all 14 sources fresh"). Links
into the full brief. Reading it *is* the "get into their mindset regularly"
habit — no dashboard visit required.

**Wednesday, 2:14pm — an alert.** Operator notification: "Brian Glass posted
2h ago about intake AI rollouts failing. Quote: '…staff comply in public and
work around the tool in private.' Suggested action: comment draft attached;
also matches objection cluster #3 (rising)." Two minutes: engage, file, or
dismiss. Engagement windows on LinkedIn are days, so this doesn't wait for
Monday.

**Anytime — the paste flow.** You see a sharp LinkedIn post or finish a
discovery call. Paste the text into the `/listening` page box (or
`listening add --source linkedin --author "..."`), tag the author, done.
Seconds later it's extracted into typed insights; call notes are flagged
primary and outrank all scraped signal. This is the system's only ask of you:
when you encounter signal, paste it.

**Before a call — prep.** `bin/autocaller listening prep "Sweet James"` prints
a one-screen brief: likely persona, the three objections to expect, the
vocabulary to use ("handoff repair," not "automation rate"), and which podcast
episode their managing partner appeared on. Thirty seconds, no tabs.

**When composing outreach — invisible UX.** You don't interact with the
listening system here at all. Drafts in the existing approval queue simply
arrive better: rationale cites the brief version and the verbatim quotes used,
and the email reads like someone who has worked an intake desk. Approve/edit
exactly as today.

**Master-agent proposals.** In the agents approval surface, listening-derived
proposals appear with evidence: "Objection 'AI notes drop emotional context'
up 40% this month — proposed composer-variant tweak attached." Approve or
dismiss; nothing sends itself.

**When it breaks — it tells you.** "r/LawFirm poller stale 9 days" arrives as
an alert. Silence means healthy, not dead — the inverse of the March failure
mode.

**The `/listening` page** (visited occasionally, not daily): rendered current
brief; insight search ("objections, from intake managers, about voice AI" →
quoted, linked, dated); source health panel (green/yellow/red); paste box;
proposed-sources queue with enable buttons.

## Cautions

- The strategy doc's own warning applies to this design: scraped signal is secondary. Keep primary-conversation items ranked highest, and treat the system as the *storage* for the twenty honest intake-manager conversations, not a substitute.
- Keep extraction verbatim-first. Paraphrase drifts toward vendor language; quotes are what make outreach sound native.
- LinkedIn: paste, don't scrape.
- The system deliberately has **no send path**. Its only outputs are the brief, search, and digests — consumed by you, the composer, and Alex's prompts.
