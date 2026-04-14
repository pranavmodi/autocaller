# Self-improving autocaller — how to get to actual booked meetings

> Goal: the system learns from every call — gets better at reaching decision-makers, running good discovery, and closing a demo slot. Not "self-learning" as a marketing term. Concrete, debuggable feedback loops.

There is no single "make it self-improving" button. The right architecture is **several stacked feedback loops**, each running on a different cadence, each targeting a different lever. The loops are:

| cadence | what changes | feedback source |
|---|---|---|
| **Per-call (real-time)** | AI's live response | the prompt; tool results |
| **Nightly** | Quality score per call | judge LLM reviews transcripts |
| **Weekly** | Prompt + objection library | aggregate judge scores + outcomes |
| **Monthly** | Lead sourcing + scoring | actual demos booked → closed |

Build them in that order. Each loop earns the right to exist by making the next one's signal cleaner.

---

## What we want to optimize (the funnel)

```
  Dialed
   │
   ├─► Connected (phone picked up)
   │     │
   │     ├─► Reached a human (not VM)
   │     │     │
   │     │     ├─► Right person (decision-maker)
   │     │     │     │
   │     │     │     ├─► Surfaced pain (discovery worked)
   │     │     │     │     │
   │     │     │     │     ├─► Agreed to demo
   │     │     │     │     │     │
   │     │     │     │     │     ├─► Demo booked on Cal.com
   │     │     │     │     │     │     │
   │     │     │     │     │     │     ├─► Demo actually happened (show rate)
   │     │     │     │     │     │     │     │
   │     │     │     │     │     │     │     └─► Closed a deal
```

Each transition has a distinct leak. Measuring where we lose people is step one. The signal at each stage:

| stage | signal | lever |
|---|---|---|
| Dialed → Connected | Twilio `answered_by` / duration > 0 | time of day, number reputation, list hygiene |
| Connected → human | AMD result + first 10s of transcript | AMD tuning, greeting |
| Human → right person | `was_gatekeeper` / `is_decision_maker` capture | lead sourcing, opener |
| Right person → pain | pain_point_summary non-empty, interest ≥ 3 | discovery script |
| Pain → agreed | transcript contains commitment phrases | pitch, objection handling |
| Agreed → booked | `demo_booking_id` non-null | Cal.com config, calendar tool |
| Booked → attended | Cal.com show/no-show webhook | demo reminders, quality of lead |
| Attended → closed | CRM lookup | sales execution (human) |

We already store most of these. The loops turn them into actions.

---

## Loop 1 — Judge LLM: daily call scoring

**The single highest-ROI thing to build first.** Every completed call gets a second-pass LLM review that scores it against a rubric and flags what went wrong.

### What it does
After each call ends:
1. A background worker pulls the transcript + metadata + the prompt version used
2. Sends to GPT-4o-mini with a rubric system prompt
3. Receives structured JSON: `{opening_quality, discovery_quality, tool_use_correctness, objection_handling, closing_quality, overall, missed_opportunities: [str], ai_errors: [str], recommended_prompt_edits: [str]}`
4. Stores on call_logs.judge_score + judge_notes

### Why it matters
- **Quantifies quality** per call, not just per outcome. A call that ended `not_interested` can still score 9/10 if the AI handled it gracefully. A `demo_scheduled` call can score 4/10 if the AI had to badger.
- **Surfaces patterns**. "Over the last 50 calls, 30% got stuck on objection type X" → actionable.
- **Cheap**. $0.02 per call with GPT-4o-mini. $20/day even at 1000 calls.
- **No risk**. Just observation, doesn't modify anything yet.

### Concrete rubric
```
opening_quality          0-10  Did the AI open with permission, get to point fast?
discovery_quality        0-10  Did it ask a quantifying question about pain?
tool_use_correctness     0-10  Right tool at right time; no hallucinated bookings
objection_handling       0-10  When pushed back, did it respond sensibly?
closing_quality          0-10  Graceful exit on yes AND on no?
overall                  0-10  Would you let this AI represent your company?

missed_opportunities     []    Free-text: what pain-signal did it miss?
ai_errors                []    Free-text: what did the AI say that was wrong?
recommended_prompt_edits []   Free-text: specific changes to try
```

### Build effort
- `app/services/judge.py` — 1 async function + schema: **2 hours**
- Background worker (asyncio task in daemon startup, picks unjudged calls): **1 hour**
- Migration to add judge columns: **30 min**
- Frontend: show score + notes on call detail page: **1 hour**
- Aggregate dashboard on Health page: **1 hour**

**Total: ~half a day.** This is Phase A — the unlock for everything that follows.

---

## Loop 2 — Prompt A/B with automatic winner selection

Once we have judge scores, we can **A/B test prompt variants automatically**.

### Mechanism
1. `app/prompts/variants/v1.py`, `v2.py`, …
2. Each call randomly picks a variant (weighted by recent win rate; start 50/50)
3. Call log stamps `prompt_version`
4. Nightly job: compute composite score per version
5. Weight the selection probability toward winners (epsilon-greedy, 10% still explores losing variants)
6. After N calls, lock in winner. Archive losers to `app/prompts/variants/archive/`.

### What to A/B test
- Opening line phrasing
- Whether we ask permission first or lead with the pitch
- Pitch one-liner vs. three-bullet version
- Transfer question phrasing
- How hard we push after first "not interested"

### Build effort
- Prompt-variant registry + random selection: **3 hours**
- `prompt_version` column + dispatch: **1 hour**
- Weekly winner-selection script: **2 hours**

**Total: ~1 day.** Phase B.

### Guardrails
- **Never silently replace v1 with v2**. Archive with a changelog entry so we can roll back.
- **Invariants are hard rules**: every variant must pass the simulator test suite (the `scripts/simulate.py` we already built) before it's allowed in production rotation.
- **Minimum sample**: no winner declared with < 50 calls per variant.

---

## Loop 3 — Objection library that grows

The third loop uses the judge's `missed_opportunities` + `ai_errors` to **auto-expand the prompt** with targeted "if they say X, respond Y" rules.

### Mechanism
1. Weekly cron aggregates judge notes: "AI got stuck on objection X" → cluster similar phrasings
2. For each cluster with ≥ 5 instances, a second LLM pass generates a draft response ("when a lead says 'we already have a CRM', the AI should respond...")
3. Draft is added to a **pending changes** queue, not auto-merged
4. Human (you) reviews queue weekly, approves → appended to the prompt as an "If X, respond Y" section
5. Simulator tests run on the new prompt before it goes live

### Why not fully automatic?
Two reasons:
1. **Style drift**. Auto-editing prompts compounds weirdness over time. Human review every week keeps the voice consistent.
2. **Legal**. Cold-calling attorneys means any wording change has compliance implications (TCPA, state bar rules). A human sign-off is cheap insurance.

### Build effort
- Clustering script (GPT-4o on judge notes): **3 hours**
- Pending-changes UI + approve button: **3 hours**
- Append-and-recompile prompt flow: **2 hours**

**Total: ~1 day.** Phase C.

---

## Loop 4 — Outcome-truthed lead scoring

The longest feedback loop. **Did the lead actually become a customer?** Takes weeks to truth but is the most valuable signal.

### Mechanism
1. When `book_demo` succeeds, Cal.com knows the meeting time
2. Webhook from Cal.com on attendance → mark `demo_attended=true/false` on call log
3. Manual CRM entry (or HubSpot webhook): mark `deal_closed=true/false` + deal_value
4. Nightly training:
   - For each lead that closed → pull their firm profile from Mission Control
   - Build a classifier on: firm_size, practice_area, state, DM title pattern, tier, etc.
   - Predict "likely-to-close" score for remaining leads
   - Rerank the pipeline

### Why this is the most important loop
Without it, every other loop is optimizing for a proxy (book rate) that doesn't necessarily correlate with revenue. You can have 100% book rate and 0% close rate if the leads are wrong. This loop is the only one that lets the system learn which leads actually matter.

### Practical shortcuts
- Start with just: "did they attend the demo" → even 10 attended / 20 booked tells you a lot
- As sample size grows, layer on close outcome
- Rerank in the pipeline: leads "look like" closers get priority, leads "look like" no-shows get deprioritized

### Build effort
- Cal.com webhook handler + schema: **3 hours**
- Manual "deal closed" field on call detail UI: **1 hour**
- Weekly classifier training (start with logistic regression on a handful of features): **1 day**
- Pipeline reranker: **3 hours**

**Total: ~2 days** — spread over weeks as the first demos actually happen.

---

## Loop 5 — Time-of-day + cadence bandit

A quiet, always-on loop that learns **when** to call.

### Mechanism
- Every dispatcher tick, instead of "call the highest-priority lead now", use a multi-armed bandit over (state × hour-of-week)
- Start with uniform exploration (10% of dials go to random slots)
- Reward = connect × (1 + interest_level bonus)
- Within 2-3 weeks we know e.g. "Tuesday 10am PT gets 42% connect rate in CA, Wednesday 3pm PT gets 18%"

### Build effort
- Bandit state table + update: **4 hours**
- Per-state-per-hour time-zone-correct window enforcement: **3 hours**

**Total: half a day.** Phase D, or whenever call volume justifies it.

### Caveat
Minimum sample per bucket is real. 7 states × 40 business hours = 280 cells. Need >10 calls per cell before any bucket's estimate is meaningful. Below that, prefer the prior (current per-state window).

---

## Loop 6 — Simulator as the CI gate

The simulator (`scripts/simulate.py`) we already built is the **safety gate** that lets all this be safe:

- Every prompt change runs through the simulator's 12-persona test suite first
- If any persona previously scored X and now scores X - 2 or worse, the change is blocked
- The gatekeeper persona must still produce `gatekeeper_only`; the ideal persona must still produce `demo_scheduled`; etc.

Without this, any auto-edit loop (objection library, A/B variants) can silently regress. With it, we can iterate fast because any regression fails the build.

### Build effort
- Baseline snapshot per persona: already done (`data/simulations/*/verdict.json`)
- Diff script: **2 hours**
- Fail-on-regression CI hook: **1 hour**

**Total: ~half a day.** Phase B dependency.

---

## Suggested 6-week sequence

| week | what to ship | unlocks |
|---|---|---|
| **1** | **Phase A: Judge LLM scoring** + UI surfacing | visibility into quality per call |
| **2** | **Simulator as CI gate** (Loop 6) | safe-to-iterate |
| **3** | **Phase B: Prompt A/B + auto-winner** | first compound learning |
| **4** | Cal.com demo-attended webhook + deal-closed field | outcome truth starts |
| **5** | **Phase C: Objection library** (human-reviewed) | prompt matures |
| **6** | **Phase D: Time-of-day bandit** + Lead reranking | throughput + quality up |

By end of week 6, the system has 4 active feedback loops, a quality score per call, and provable regression protection. Volume determines how fast each loop's sample size gets useful.

---

## What to measure weekly

A single page — Monday morning digest:

1. **Calls this week** (and vs. last week)
2. **Funnel conversion** at each stage
3. **Judge score** distribution (mean, 25th/50th/75th) + drift vs. last week
4. **Per-prompt-version** stats (if A/B running): book rate, judge score, avg interest level
5. **Top 3 missed-opportunities clusters** (from judge notes)
6. **Top 3 objection types** that blocked bookings
7. **Leads touched / leads remaining** per tier, per state
8. **Cost per booked demo** — Twilio + OpenAI + judge LLM, all-in

If a number moves > 20% week-over-week, the digest calls it out red or green. That's your weekly review meeting agenda.

---

## What this does NOT include (and why)

- **RL fine-tuning of a custom voice model.** Wrong tool. We don't have 10k+ labeled examples, and closed-model fine-tuning is expensive vs. prompt optimization.
- **Auto-commit prompt edits without human review.** Compounds weirdness; small drifts become large over months. Keep a human in the weekly loop.
- **Scraping additional lead sources automatically.** Sourcing is a different kind of problem — closer to a data pipeline than a conversation loop. Out of scope here; see `docs/VISION.md` Phase 2.
- **Multi-agent orchestration (e.g. AI manager AI critiquing caller AI live).** Cute, but the judge loop + human review covers the same ground with less surface area to get wrong.

---

## Honest caveat

"Self-improving" implies the system gets strictly better over time without supervision. In practice:

- **Iterating on an agent in a closed loop is a high-variance process.** It will get worse on some dimension for a week before something clicks.
- **Sample size is the bottleneck.** You need real call volume before any loop produces a signal worth acting on. At 10 calls/week, this is theater. At 200 calls/week, it starts mattering. At 1000 calls/week, it's the difference between a product and a toy.
- **The human is not optional.** Every one of these loops has a human step — review the judge flags, approve the objection additions, inspect the bandit winners. Self-improving is a force multiplier, not a replacement for reading transcripts.

The right question isn't "how do I make it self-improving" — it's "what's the smallest feedback loop I can ship this week that gets me closer to a booked demo that closes?" That's **Phase A (judge LLM scoring)**. Build it, watch it flag 10 things you didn't see, fix those, and the next phase will be obvious.

---

## Recommendation

Ship Phase A **this week**. It's half a day of work, costs pennies per call to operate, and reveals the truth about whether the pipeline is actually working. Everything else earns the right to exist by pointing at data Phase A produced.
