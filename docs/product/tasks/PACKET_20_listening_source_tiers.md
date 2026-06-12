# Packet 20 — Listening: source-kind filters + quality tiers + tier-aware synthesis

You are the implementer in /root/.openclaw/workspace/mission-control. The
listening system (backend/listening.py, frontend listening page) ingests
podcasts, blogs/substacks, RSS, reddit, and call transcripts into
listening_sources/listening_items/listening_insights (+ mindset briefs,
alerts, chat). Operator finding: reddit insights are noisy; podcasts and
blogs carry higher-quality operator voices. Build source-kind filtering and
a quality-tier system so high-quality sources lead.

## Read first
- backend/listening.py (insights endpoints, source rows, synthesis prompt,
  exec view payloads, chat citation retrieval)
- frontend listening page component(s) (collapsible sections, exec view,
  insight cards, source rows)
- The import fallback convention at the top of backend/listening.py
  (service runs from backend/ as CWD — keep it intact)

## Build

### 1. Schema (additive, sqlite)
- `listening_sources.quality_tier TEXT NOT NULL DEFAULT 'B'` with values
  'A'|'B'|'C'. Backfill defaults by kind: podcast->'A', blog->'A',
  rss->'B', paste/pointer->'B', reddit->'C', call->'B'. Migration must be
  idempotent (CREATE/ALTER IF NOT EXISTS pattern used elsewhere in the
  file).

### 2. API
- Insights list endpoint(s): add `kind=` (comma-list of source kinds) and
  `min_tier=` ('A'|'B'|'C', meaning that tier or better) filters; include
  `source_kind` and `quality_tier` on each returned insight row (join via
  item -> source).
- Default ordering everywhere insights are listed: quality_tier ASC
  ('A' first), then the existing primary/recency ordering. Keep existing
  params working unchanged.
- `PATCH /api/listening/sources/{id}` accepts `quality_tier` (validate
  A|B|C).
- Exec view endpoint: accept `min_tier` (default 'B' = A+B only) and a
  way to request all.

### 3. Frontend (listening page)
- Filter chips above the insights list: All / Podcasts / Blogs / Reddit /
  Calls (blogs chip covers blog+rss+substack kinds). Chip state drives the
  kind= param. Persist last choice in localStorage.
- Tier badge on every insight card (A/B/C, small colored chip: A=emerald,
  B=neutral, C=amber) and on source rows.
- Source rows: tier is editable (small select or click-to-cycle chip) via
  the PATCH endpoint.
- Exec view: defaults to A+B with a "show all sources" toggle wired to
  min_tier.

### 4. Tier-aware synthesis + chat
- Mindset-brief synthesis: when assembling evidence for the LLM, label
  each quote with its tier and add an instruction: tier-A quotes are
  primary evidence; tier-C (reddit) may only corroborate frequency
  ("appears N times in r/...") and must not be the sole basis of any
  claim. Keep prompt change minimal and visible in one place.
- Chat citation retrieval: when multiple sources support a passage,
  prefer higher tiers in ranking (tier as a sort key before similarity
  tie-break, do NOT exclude lower tiers).

### 5. Tests + validation
- Whatever test conventions exist in the repo; otherwise add focused
  pytest covering: tier backfill by kind, kind/min_tier filter SQL,
  ordering (A before C at equal recency), PATCH validation.
- Validation (include output): migration on the live DB (it is additive);
  curl insights with kind=reddit, kind=podcast, min_tier=B against live
  data showing counts; PATCH one source tier and revert it; screenshot-
  level description of the chips/badges; npm/next build passes if the
  frontend has a build step (check how it is served).

## Constraints
- Do NOT touch the email/autocaller repo. Do NOT restart services — the
  operator orchestrator handles deploy/restart after review.
- The MC backend serves live traffic; migration must be additive and the
  code backward-compatible until restart.
- LLM/gateway calls: none needed for this packet (the synthesis prompt
  change is text only — do not run a synthesis).
- listening extraction queue: do NOT queue extraction batches.

## Done when
Insights are filterable by source kind, every insight/source shows an
editable quality tier, A-tier floats everywhere by default, the exec view
defaults to A+B, and the brief/chat treat reddit as corroboration rather
than primary evidence.
