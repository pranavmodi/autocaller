# PACKET LEXVIS L3 — McKinsey-style report v2 (render stage + report page)

Workdir: `/home/pranav/lexvisibility`. Read first: `app/pipeline.py` (stages,
artifact contracts), `frontend/app/r/[token]/` (current report page),
possibleos `docs/decisions/2026-07-06.md` D-01 (the philosophy this packet
implements), `docs/lexvisibility-2-spec_updated.md` §2.6.

You are Codex. Do NOT commit/push, restart services, or call any LLM — every
section below is deterministic template assembly from upstream artifacts.

## Why

The report must make the founder conclude three things on his own: these
people obviously know what they're talking about (specificity), this is too
complex for DIY or a generalist SEO agency (complexity made legible), and
the upside justifies paying (prize, not just loss). Discipline rule enforced
in code: **every factual claim traces to an upstream artifact field** — the
render payload carries `traces: [artifact_stage.field_path]` per section.

## Scope

### 1. Extend the ingest stage (bump artifact, backward compatible)

Also import from the aiscan DB (read-only; discover exact tables/columns by
reading /home/pranav/ai-visibility/app — do not guess): `website_signals_json`
(basics, gaps, competitor contrasts), stored recommendations rows, and the
per-observation accuracy flags if not already inside `observation_json`.
Add keys `website_signals`, `recommendations`, `accuracy_flags` to the ingest
payload. Existing keys unchanged.

### 2. Render stage v2 — the 8-section payload

Replace the render payload's top-level shape with `sections: [...]`, each
`{id, so_what, executive_view, body, traces}` in this order (keep
`hero_evidence`, `report_token` handling, and the QA gate exactly as-is):

1. `executive_summary` — verdict line, monthly range, thesis sentence:
   "Your rivals aren't better lawyers; they're better represented in the
   data AI reads." Counts from score.headline; dollars from dollarize.
2. `evidence` — query×run grid + leaderboard + verify-yourself block
   (existing data, now with a so_what header: "This is reproducible — run
   the query yourself").
3. `mechanism` — per top-3 leaderboard rival: which cited surfaces carried
   them (from ingest cited_urls per query-run where that rival appeared:
   group cited domains — directories, review platforms, own-site pages) +
   the website competitor-contrast entries from website_signals. Named,
   specific, no adjectives.
4. `why_hard` — assembled from data: (a) run-to-run variance measured in the
   grid (count of queries whose runs disagree), (b) the multi-surface list
   observed in 3 (count distinct cited domains), (c) accuracy_flags count
   ("AI answers also carry N wrong/unverifiable claims — visibility work
   includes correcting the record"), (d) static drift copy: answers shift as
   models retrain; one-time fixes decay silently. Executive view: this is a
   standing capability (instrument, fix, re-measure), not a project.
5. `prize` — upside model from leaderboard + dollarize: monthly value of the
   #1 slot-holder's share (top rival weighted_appearances / total answering
   runs × base dollars), the same for a realistic #3 slot, phrased as
   "currently held by <rival>". All inputs shown.
6. `first_moves` — top 3 recommendations from ingest.recommendations that
   are website/profile fixes (LA market page, structured data, third-party
   profile cleanup), each with its evidence pointer. Labelled "free — do
   these regardless of who you work with".
7. `campaign` — workstream-shape only, parameterized with firm/market/rival
   names and measurable targets from the data: four workstreams (site
   structure, citation graph, review corpus, standing measurement) × ~90-day
   arc × "winning looks like: appearing in ≥N of the 20 answering runs on
   re-scan". No operating detail beyond workstream names.
8. `cta` — "Worth 20 minutes to walk through the full plan? Reply and I'll
   send two times." (mailto from existing CTA block).

### 3. Report page v2 (`frontend/app/r/[token]`)

Render the sections array: each section = bold serif so_what headline,
smaller-caps "Executive view" one-liner, then the body blocks (reuse
existing grid/leaderboard/worksheet components inside their sections).
Section 7 gets a simple 90-day horizontal timeline (pure CSS, no new deps).
Keep the memo design: serif headings, no gradients, mobile-first 390px,
sticky CTA footer. Pre-QA behavior unchanged.

### 4. Stage-rail compatibility

The `/runs/[id]` artifact viewer must render the new render-payload shape
without errors (its generic JSON viewer likely already does — verify).

## Guardrails (hard)

- No LLM calls, no network calls; aivis DB strictly read-only (mode=ro).
- Additive to pipeline contracts: ingest keys added, render reshaped —
  update the pipeline tests accordingly, do not weaken existing assertions
  (hash stability, versioning, QA gate, 403 pre-approve).
- Do NOT touch resolve/score/dollarize logic. Do NOT touch nginx/systemd.
- Do NOT `git commit`/`git push`.

## Validation (run, report)

- `pytest tests/ -q` green; new tests: ingest v2 carries website_signals /
  recommendations / accuracy_flags from the fixture DB; render payload has
  exactly the 8 sections in order, each with non-empty so_what and traces;
  prize numbers recompute from leaderboard+dollarize inputs; report endpoint
  still 403 pre-QA.
- `cd frontend && npm run build` and `npm run lint` clean.
- Do NOT rerun the real Block LLP run (orchestrator does live verification).

## Report (end of run)

Files changed, the section schema, which fixture fields feed sections 3–6,
test + build output, and STOP.
