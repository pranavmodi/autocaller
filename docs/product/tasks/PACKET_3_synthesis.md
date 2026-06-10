# Packet 3 — Synthesis: versioned mindset brief + digest

You are the implementer. Depends on Packet 2A (insights exist).

## Read first
- /home/pranav/autocaller/docs/product/LISTENING_SYSTEM_IMPLEMENTATION_PLAN.md (Phase 3)
- /home/pranav/autocaller/docs/product/LISTENING_SYSTEM_DESIGN.md (§4 + User experience — digest content)
- backend/listening.py; main.py's strongest-model Anthropic usage (synthesis
  warrants the better model, unlike bulk extraction)

## Objective
Weekly synthesis job producing a versioned markdown mindset brief, plus brief
retrieval/search APIs and a digest payload.

## Tasks
1. `POST /api/listening/synthesize` (BackgroundTasks): gather insights since
   last brief (all, if first run); weight `is_primary` items above scraped;
   one strong-model call structured as the brief sections: Top clusters +
   trend deltas vs. previous brief stats, Objection library (objection →
   suggested counter, with verbatim quotes), Vocabulary glossary, Persona
   notes, Leader tracker (latest take per tracked person), What changed this
   week. Insert `mindset_briefs` row (version = max+1, stats_json = cluster
   counts used for the next delta).
2. `GET /api/listening/brief` (latest, `?version=N`), `GET
   /api/listening/briefs` (version list).
3. `GET /api/listening/digest` — compact JSON of the latest brief's "what
   changed" + top quotes + source-health line (sources where now -
   last_polled_at exceeds 2× expected cadence; add `expected_cadence_days`
   column, default by kind: rss/reddit/podcast 7, blog 30).
4. `deploy/listening/bin/synthesize_weekly.sh` + matching
   `mc-listening-synthesize.{service,timer}` (weekly, after the poll timer):
   POST synthesize, then GET digest and email it using the same mechanism MC
   already uses to send mail — if MC has none, write the digest to
   `data/digests/digest-vN.md` and print a TODO line for the orchestrator
   (autocaller's email service will deliver it in Packet 4/5).
5. Render the brief on the `/listening` page (markdown render, version picker)
   — only if Packet 2B's page exists; otherwise skip silently.

## Constraints
- No restarts; temp uvicorn 18001; one synthesize call max during validation.
- Brief must store markdown, not HTML.

## Validation (include output)
- Run synthesize once on real insights → brief v1 with all six sections and
  ≥5 verbatim quotes that exist in listening_insights.
- Run again → v2 exists and its trend section references v1's stats.
- digest endpoint returns the v2 delta + health line.

## Done when
Two real brief versions exist with a genuine delta; digest payload correct;
weekly unit written for the orchestrator to install.
