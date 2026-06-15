# Mental Model v2: one agent, not a pipeline

*2026-06-11, revising the earlier audit after: Front provenance investigation,
master-agent architecture review, and the operator brain dump (autonomous
campaign system that understands the offer + market, sharpens ICP over time,
researches leads, composes personalized comms, executes daily, keeps itself
updated). See docs/product/BUSINESS_CONTEXT.md.*

## 1. The Front corpus: provenance answered

- **Source**: Precise Imaging's production Front instance
  (`precise-imaging.api.frontapp.com`); credentials live in
  `/root/.openclaw/workspace/secrets/front_precise.env`.
- **How it lands in MC**: standalone crawl scripts in
  `/root/.openclaw/workspace/scripts/` (`lien_cache_crawl.py`,
  `bulk_crawl*.py`) page the Front API rate-limited and `INSERT OR REPLACE`
  into mission.db (`front_conversations`, `front_messages`). Freshness comes
  from the OpenClaw assistant's **"Negotiations crawl" cron every 4h** — the
  same job that's been restarting MC. Coverage: Aug 2019 → today, 25.7k
  conversations / 106.7k messages.
- **Raw or processed**: **raw** — full message bodies with author
  email/name and an inbound flag. The only processing so far is lien-specific
  (`batch_analyze_negotiations.py` → `lien_negotiations`). There is **no PII
  handling anywhere in that path** — patient names/DOBs/case details flow
  uncensored into mission.db. Fine as Precise's operational cache; a hard gate
  is required before one byte of it feeds outreach or the listening corpus.

## 2. The master agent: what exists

- **Design (docs/MASTER_AGENT_CONTEXT_ARCHITECTURE.md)** is exactly the brain
  the brain dump asks for: two prime directives (move fast toward user goals;
  maintain and improve a mental model of the system), a goal stack by horizon,
  wake context as a "control cockpit" (directives → goals → operating state →
  mental model → evidence → capabilities → decision frame), three context
  layers tuned for prompt caching, and heartbeat continuity (previous
  heartbeat event, durable actions, goal evidence, task board, reports).
- **Implementation** is early but real: 9 goals, 19 capabilities, 11 durable
  actions, 12 reports in postgres; a tool loop in `master_agent_runner.py`
  (recent commits: tool runner actions, read-only FS inspection, durable email
  actions); `/agents` page shows heartbeat I/O. The implementation plan is
  sliced (wake-context v2 skeleton → objective status → …) and uncommitted
  WIP continues it.

## 3. Does the brain dump change the model? Yes — one fundamental shift

My audit treated the fixes as **subsystems to wire together**: a lead engine,
an observations pipe, a weekly policy cron, a composer upgrade. The brain dump
plus the master-agent design says these are not separate systems — they are
**organs of one agent**, and the master agent is that agent:

- *understands what we offer* → mental-model section of wake context (the
  Precise tools, the wedge, the case study)
- *understands the market / sharpens ICP* → listening corpus + Front
  engagement data, distilled into a **versioned ICP artifact** the agent
  updates with evidence
- *researches lead company and contact* → tool calls (pif_firms, website
  crawl, Front history, listening insights per firm)
- *composes personalized communications* → skills (blog-outreach-composer
  pattern), invoked per lead with research + brief + quotes
- *executes a daily campaign* → the heartbeat: select → research → compose →
  queue for approval → send → observe yesterday → adjust
- *keeps itself updated* → the timers already feeding listening + Front cron
  + health watchdog; prime directive #2 makes model-updating the agent's job

The shift in one sentence: **stop building a pipeline with a weekly batch
job; finish the master agent and give it the lead-gen goal as its daily
heartbeat.** The "weekly policy iteration" from the audit collapses into the
agent's own observe-orient step, running daily.

## 4. Revised top moves

| # | Move | Change vs audit |
|---|---|---|
| 1 | **Front engine with PII gate first** — warm-lead scoring (recency × frequency × seniority) into contact selection; firm-side ops content (post-scrub) into listening as primary items | Unchanged priority; expanded purpose: it's also offer-understanding (our tools live in those threads) and ICP ground truth (who actually engages) |
| 2 | **Auto-observations** — every delivery/reply/call/booking event writes lead_gen_observations, no human in path | Unchanged — the agent is blind without it |
| 3 | **Master-agent lead-gen heartbeat** — daily loop per the architecture doc's slices: wake context v2 + the lead-gen goal; select/research/compose/queue-for-approval daily; human approves sends (keep the gate) | **Replaces** the standalone weekly-policy cron; pulls forward what was deferred as "5.4" |
| 4 | **ICP as a versioned artifact** — `icp_profile` vN (dimensions from GTM doc + Front engagement evidence), updated by the agent when evidence accumulates, consumed by selection + composer | **New as first-class** (was implicit); this is "define the ICP and sharpen it over time" made concrete |
| 5 | **Composer skills** — per-lead personalized comms as skills the agent invokes (research + Precise evidence block + corpus quotes), email first, phone script second | Was two moves (evidence block + variant); unified as the agent's hands |
| 6 | **Volume ramp 5→25/day with deliverability guardrails** | Unchanged, now agent-managed |
| 7 | **Voice decision** — 50-call Precise-warm experiment or explicit pause | Unchanged |
| — | Todo #42 (knowledge-layer migration) | Gets pulled earlier: the agent lives in autocaller and shouldn't depend on MC sqlite for its senses |

**KPI stands**: learn on qualified engagements/week, report on booked
conversations. The agent's daily heartbeat makes the learning cadence daily
instead of weekly — the cycle-time term improves another 5–7×.

## 5. Sequencing (revised)

1. **PII scrub gate + Front contact/engagement extraction** (it gates
   everything; adversarial tests before any data flows)
2. **Auto-observations** (small, immediate; the agent's senses)
3. **Master-agent wake-context slice + lead-gen goal** (per the existing
   implementation plan; daily heartbeat composing approval-ready outreach)
4. **ICP artifact v1** (seeded from GTM doc + first Front engagement data)
5. Composer skills with Precise evidence; then volume ramp; then the voice
   experiment — all executed and measured by the agent.

Human approval stays on every outbound send until the loop has earned trust
with weeks of clean evidence — that gate is the cybernetic design's own rule.
