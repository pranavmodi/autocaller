# Listening System — Implementation Plan

*2026-06-09. Concrete next-step plan for the design in `LISTENING_SYSTEM_DESIGN.md`,
which itself executes the "listening system" thread of `GTM_STRATEGY_2026-06.md`.*

## Decisions (locked unless revisited)

| Decision | Choice | Rationale |
|---|---|---|
| System of record for capture/extraction/synthesis | **Mission Control** (`/root/.openclaw/workspace/mission-control/`, FastAPI on :8001, sqlite `data/mission.db`) | Reddit crawler, PILMMA crawler, podcast transcription queue, paste-transcript flow all already live there |
| Autocaller's role | **Read-only consumer** via MC API on loopback | Composer + discovery prep need the brief; autocaller never ingests |
| Scheduling | **systemd timers** running `curl` against the existing MC endpoints | No code change to trigger recurrence; observable via `systemctl list-timers`; matches how MC services are already run |
| LinkedIn | **Manual paste only** | No API; scraping is ToS-risky. Paste is a first-class channel |
| Extraction style | **Verbatim-quote-first, LLM structured output** | Mirrors the `yelp-review-quotes` skill; quotes are the asset |

## Phase 1 — Make existing capture recur (no new schema)

Everything in this phase drives endpoints that already exist in
`backend/main.py`.

| Task | How | Existing code |
|---|---|---|
| 1.1 Analyze the 696 backlogged Reddit posts | Loop `POST /api/research/reddit/analyze-batch` until `analyzed=0` count is 0 | `reddit_analyze_batch` (main.py:3720), `reddit_analyze_post` (main.py:3680) |
| 1.2 Weekly Reddit crawl + analyze | systemd timer `mc-reddit-weekly.timer` → `POST /api/research/reddit/crawl`, then analyze-batch | `reddit_crawl` (main.py:3595) |
| 1.3 Monthly PILMMA re-crawl (incremental) | Timer → `POST /api/research/crawl` then `POST /api/research/analyze`. Verify `do_crawl` (main.py:1819) skips known URLs; add a URL-dedup check if not | `do_crawl`, `do_analyze_posts` (main.py:1954) |
| 1.4 Weekly podcast refresh + auto-transcribe shortlist | Timer → `POST /api/pi-podcasts/refresh`, then `POST /api/pi-podcasts/{id}/transcribe-new` for each shortlisted show | `refresh_pi_podcasts` (main.py:5376), `transcribe-new` (main.py:6228), `_pi_transcribe_worker` queue (main.py:602) |
| 1.5 Reddit consolidation refresh | Monthly timer → `POST /api/research/reddit/consolidate` | `reddit_consolidate` (main.py:3775) |

**Podcast shortlist** (match `pi_podcasts.title`): Maximum Lawyer, Personal
Injury Mastermind, Trial Lawyer Nation, Elawvate, LawDroid Manifesto. ~5 new
episodes/week total — cheap, and aimed at the 10 thought leaders in the GTM doc.

**Deliverables:** `deploy/mc-listening-*.{service,timer}` units + an
`ops/listening_phase1.sh` that runs the backlog analysis once.
**Acceptance:** `reddit_posts` has rows with `fetched_at` in the current week;
`analyzed=0` count is 0; shortlist shows gain new `status='done'` transcripts
without manual clicks.

## Phase 2 — Unified corpus, new sources, extraction

### 2.1 Schema (new tables in `mission.db`)

```sql
CREATE TABLE listening_sources (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL,         -- rss|reddit|podcast|blog|linkedin|paste|job_listing|call
  name TEXT NOT NULL, url TEXT, person TEXT,          -- person = thought-leader name if applicable
  enabled INTEGER NOT NULL DEFAULT 1, last_polled_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE listening_items (
  id INTEGER PRIMARY KEY, source_id INTEGER REFERENCES listening_sources(id),
  external_ref TEXT,                                   -- e.g. 'reddit_posts:101', 'pi_podcast_episodes:204', URL
  author TEXT, title TEXT, url TEXT, published_at TEXT,
  raw_text TEXT NOT NULL, content_hash TEXT UNIQUE,
  is_primary INTEGER NOT NULL DEFAULT 0,               -- 1 = discovery call / direct conversation; ranked above scraped
  status TEXT NOT NULL DEFAULT 'new',                  -- new|extracted|skipped|error
  fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE listening_insights (
  id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES listening_items(id),
  type TEXT NOT NULL,        -- pain_point|objection|vocabulary|belief|metric_they_trust|adoption_story|vendor_sentiment
  cluster TEXT, quote TEXT NOT NULL, paraphrase TEXT,
  who_feels_it TEXT,         -- managing_partner|intake_manager|paralegal|case_manager|office_manager|unknown
  severity TEXT, confidence REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE mindset_briefs (
  id INTEGER PRIMARY KEY, version INTEGER UNIQUE NOT NULL,
  brief_md TEXT NOT NULL, stats_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 New ingestion

- **RSS/Substack poller** — `GET feed_url` (every Substack exposes `/feed`),
  parse with `feedparser` (add to `backend/requirements.txt`), full-text fetch
  with existing httpx+bs4 boilerplate-stripping from `do_crawl`. One adapter
  covers all Substacks + firm blogs. Endpoint: `POST /api/listening/poll`
  (all enabled rss sources), reusing the `do_transcribe`-style BackgroundTasks
  pattern. Weekly timer.
- **Paste channel** — `POST /api/listening/paste` (`{source_kind, author,
  url?, text}`) → creates item with `is_primary=1` for call notes; UI textarea
  on the new `/listening` page (clone the paste-transcript flow at main.py:1593).
- **Adapters from existing tables** (no re-crawling): nightly task copies new
  rows into `listening_items` via `external_ref`:
  `reddit_posts` (title+selftext+comments_text), `research_posts` (body),
  `pi_podcast_episodes` where `status='done'` (formatted_transcript, chunked
  ~8k tokens/item), `job_listings`, `customer_calls`/`transcriptions`
  (`is_primary=1`).

### 2.3 Extraction

- `POST /api/listening/extract` — batch over `status='new'` items; one
  Anthropic structured-output call per item (taxonomy above; prompt modeled on
  `.claude/skills/yelp-review-quotes`); insert insights; mark `extracted`.
  Run from the same nightly timer after the adapter sync.
- **Backfill:** one-off script runs the adapters + extractor over all existing
  content (756 reddit, 384 PILMMA, 250 transcripts). Expect ~1.4k items; run
  in batches; this is the single biggest LLM spend in the project — do it once,
  incrementally thereafter.

**Seed `listening_sources`:** LawDroid Manifesto (Substack), Adam's Legal
Newsletter (Substack), Daniel Roche intake Substack, Legal Tech Trends,
Rankings.io newsletter, the 5 podcasts (kind=podcast, pointer only), the 6
subreddits (pointer to reddit_config), PILMMA blog (pointer), plus
`kind=linkedin` person rows for: Mutrux, Simon, Martin, Dreyer, Cowen, Glass,
Correia, Gideon, Zaid, Unikowsky (paste-fed).

**Acceptance:** `listening_items` count > 1,000 after backfill; insights exist
for all 7 types; a new Substack post appears as an extracted item within a week
with zero manual steps.

## Phase 3 — Synthesis: the mindset brief

- `POST /api/listening/synthesize` (weekly timer): cluster insights since the
  last brief, compute trend deltas vs. previous brief, regenerate one markdown
  artifact → new `mindset_briefs` row (version N+1).
- Brief sections: **Top clusters + trends** (rising/falling), **Objection
  library** (objection → counter, with quotes), **Vocabulary glossary**,
  **Persona notes** (partner vs. intake manager vs. paralegal), **Leader
  tracker** (latest take per person), **What changed this week**.
- `GET /api/listening/brief` (latest), `GET /api/listening/brief/{version}`,
  `GET /api/listening/insights/search?q=&type=&cluster=&who=`.
- **Digest:** weekly email/notification with the "what changed" section —
  reuse MC's existing notification path, or autocaller's
  `email_notification_service` after Phase 4 sync.

**Acceptance:** two consecutive weekly briefs exist with a real trend delta;
brief renders on the `/listening` page; digest lands in inbox.

## Phase 4 — Autocaller consumption (CLI golden rule applies)

1. **Service:** `app/services/listening_client.py` — thin httpx client for MC
   `:8001` listening endpoints (pattern: `pifstats_sync.py` / `leads
   sync-mission`).
2. **CLI group** in `app/cli.py`:
   - `listening brief [--version N]` — print latest mindset brief
   - `listening search "<q>" [--type objection] [--who intake_manager]`
   - `listening quotes --cluster <cluster> [--limit 5]`
   - `listening sources` — list sources + freshness (staleness alarm)
3. **Composer integration:** the insight-led composer variant
   (`lead_email_composer_variants.py`) pulls top-k insights matched on the
   firm's ICP signals + brief version; **record `brief_version` on the email
   log** alongside `prompt_version` so every send traces to the mindset
   snapshot that informed it.
4. **Discovery-prep:** `listening prep <firm>` — persona + expected objections
   + vocabulary for a specific firm before a call.
5. **Docs per golden rule:** add rows to `docs/cli.md` §3 + recipe in §10;
   update `.claude/skills/autocaller/SKILL.md` and sync the openclaw copy.

**Acceptance:** an operator (or agent) with only the CLI can read the brief,
search quotes, and see source freshness; a composed email records its
`brief_version`.

**Autocaller implementation note (2026-06-10):** `app/services/listening_client.py`
now consumes the Mission Control listening API read-only. `bin/autocaller
listening brief/search/quotes/sources/prep` exposes the operator surface.
Lead-gen email composition adds latest brief context and top matched insights
when Mission Control is reachable, and `email_logs.brief_version` is nullable so
composition and sends proceed with `NULL` when Mission Control is down.

## Proactivity model

The system must come to the operator, not wait to be asked. Four levels, each
building on the previous; Levels 0–1 are already in Phases 1–3, Levels 2–3 are
added here as Phase 5.

**Level 0 — Scheduled autonomy (Phases 1–3).** Timers run ingest → extract →
synthesize with no human trigger. The weekly digest email is the floor of
proactivity: every week the mindset brief's "what changed" lands in the inbox
unprompted.

**Level 1 — Watchdog (Phase 1, required).** The existing system's failure mode
was *silent rot* — the Reddit crawler stopped in March and nobody noticed for
three months. Every source gets a freshness SLA (`listening_sources` already
has `last_polled_at`; add `expected_cadence_days`). A daily check notifies the
operator when a source breaches its SLA or an extraction batch errors. A
proactive system's first duty is announcing its own failures.

**Level 2 — Event-driven alerts (Phase 5).** Don't make the operator wait for
the weekly digest when something time-sensitive lands. After each extraction
batch, an alert rule pass fires immediate notifications for:
- a tracked thought leader publishes anything matching the wedge topics
  (intake, after-hours, AI adoption) — engagement windows on LinkedIn/Substack
  are days, not weeks;
- a high-severity insight cluster spikes vs. trailing baseline (e.g. a burst
  of "AI demo fatigue" posts);
- a crawled item mentions Possible Minds, Precise Imaging, or a named
  competitor;
- a new voice appears repeatedly (≥3 quoted insights from an untracked author)
  → proposes adding them as a source. The source list extends itself, gated by
  operator approval.
Delivery via the existing operator-notification path; each alert carries the
quote, link, and a suggested action.

**Level 3 — Master-agent integration (Phase 5, after master-agent work
stabilizes).** Autocaller's master agent (`master_agent_runner`, `master_goals`,
heartbeats) gets a listening goal: on heartbeat it reads new insights and brief
deltas, and *proposes* actions through the existing approval flow — e.g.
"objection X is rising; here is a composer-variant tweak that addresses it,"
"firm Y in our Tier-1 list was discussed in episode Z; suggested insight-led
opener attached," "draft reply/comment for this thread by a tracked leader."
This closes the loop from listening → outreach policy, with the human-approve
gate the cybernetic design already mandates. The agent never sends; it
surfaces, drafts, and proposes.

What stays deliberately *non*-proactive: sending. Outreach, replies, and
LinkedIn engagement remain human-approved actions; the system's proactivity
ends at well-timed, well-evidenced proposals.

## Phase 5 — Proactive layer (after Phase 3)

| Task | How |
|---|---|
| 5.1 Freshness watchdog | `expected_cadence_days` on sources; daily timer → `GET /api/listening/health` → notify on breach |
| 5.2 Alert rules pass | Post-extraction hook; rules in a `listening_alert_rules` table (topic match, cluster spike, name mention, new-voice threshold); notifications carry quote + link + suggested action |
| 5.3 Self-extending sources | New-voice detector creates a *proposed* `listening_sources` row (`enabled=0`) + notification; operator enables via UI/CLI |
| 5.4 Master-agent listening goal | Add listening capability to `agent_capabilities`; heartbeat reads insights/brief deltas; proposals flow through existing approval surface |

**Acceptance:** kill a poller and get a staleness alert within 24h; a seeded
test post by a tracked leader produces an alert within one poll cycle; a
master-agent heartbeat produces at least one listening-derived proposal in the
approval queue.

## Order & effort

| Phase | Effort | Depends on |
|---|---|---|
| 1 Recurrence | ~half day (timers + backlog script) | nothing |
| 2 Corpus + extraction | ~2–3 days (schema, poller, paste, adapters, extractor, backfill) | 1 |
| 3 Synthesis + digest | ~1–2 days | 2 |
| 4 Autocaller CLI + composer | ~1 day | 3 (brief endpoint) |
| 5 Proactive layer (watchdog, alerts, master-agent goal) | ~1–2 days (5.4 waits for master-agent work to stabilize) | 2 (5.1–5.3), master agent (5.4) |

Phase 1 is pure leverage — do it first and the system is already "regular"
while 2–4 are built.

## Risks / open items

- `main.py` is 8,973 lines; put new listening code in a `backend/listening.py`
  router module rather than growing the monolith.
- Reddit's public JSON endpoints rate-limit aggressively; weekly cadence keeps
  this safe — don't shorten it without auth.
- PILMMA crawl incrementality must be verified (task 1.3) before scheduling.
- Backfill LLM cost: ~1.4k extraction calls. Use a cheap structured-output
  model (Haiku-class); reserve the strong model for weekly synthesis.
- The strategy doc's caution stands: `is_primary=1` conversations outrank all
  scraped signal in synthesis weighting. The system stores understanding —
  the twenty intake-manager conversations still have to happen.

## Todo tracking

Add to the autocaller `todos` table (area `listening`): one todo per phase,
via `bin/autocaller todos add ...`, per the CLAUDE.md rule that active backlog
lives in the DB, not markdown.
